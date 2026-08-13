from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tools.independent_review.models import (
    AgentIdentity,
    CredentialScope,
    FindingSeverity,
    ProviderReviewCandidate,
    ReviewFinding,
    ReviewTarget,
    ReviewVerdict,
)
from tools.independent_review.validator import ReviewValidationError, validate_candidate


def identity(agent: str, session: str, scope: CredentialScope) -> AgentIdentity:
    return AgentIdentity(
        role="REVIEWER" if "review" in agent else "IMPLEMENTER",
        provider="test",
        agent_id=agent,
        session_id=session,
        credential_scope=scope,
    )


def target() -> ReviewTarget:
    return ReviewTarget(
        repository="o/r",
        pr_number=1,
        base_ref="rebuild/v2-foundation",
        base_sha="a" * 40,
        trusted_base_sha="d" * 40,
        head_ref="head",
        head_sha="b" * 40,
        requested_at=datetime.now(timezone.utc),
    )


def blocking() -> ReviewFinding:
    return ReviewFinding(
        finding_id="F1",
        severity=FindingSeverity.BLOCKING,
        category="correctness",
        title="不具合",
        explanation="契約に違反しています",
        evidence=["1行目"],
        fingerprint="bug:1",
    )


def validate(candidate: ProviderReviewCandidate, *, reviewer: AgentIdentity | None = None):
    t = target()
    if candidate.echoed_head_sha is None:
        candidate = candidate.model_copy(update={"echoed_head_sha": t.head_sha})
    return validate_candidate(
        candidate,
        target=t,
        current_head_sha=t.head_sha,
        implementer_identity=identity(
            "implementer", "impl-session", CredentialScope.IMPLEMENTATION_WRITE
        ),
        reviewer_identity=reviewer
        or identity("reviewer", "review-session", CredentialScope.REVIEW_WRITE),
        context_complete=True,
    )


def test_pass_without_blocking_finding() -> None:
    decision = validate(
        ProviderReviewCandidate(verdict_candidate=ReviewVerdict.PASS, summary="問題ありません")
    )
    assert decision.verdict == ReviewVerdict.PASS
    assert decision.blocking_finding_ids == []


def test_pass_with_blocking_is_retryable() -> None:
    with pytest.raises(ReviewValidationError, match="PASS") as captured:
        validate(
            ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.PASS,
                findings=[blocking()],
                summary="不正な判定",
            )
        )
    assert captured.value.retryable is True


def test_changes_requested_requires_blocking_and_is_retryable() -> None:
    with pytest.raises(ReviewValidationError, match="BLOCKING") as captured:
        validate(
            ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.CHANGES_REQUESTED,
                summary="修正が必要です",
            )
        )
    assert captured.value.retryable is True


def test_agent_collision_is_not_retryable() -> None:
    reviewer = identity("implementer", "different", CredentialScope.REVIEW_WRITE)
    with pytest.raises(ReviewValidationError, match="AI識別子") as captured:
        validate(
            ProviderReviewCandidate(verdict_candidate=ReviewVerdict.PASS, summary="試験"),
            reviewer=reviewer,
        )
    assert captured.value.retryable is False


def test_forbidden_reviewer_scope_is_not_retryable() -> None:
    reviewer = identity("reviewer", "different", CredentialScope.IMPLEMENTATION_WRITE)
    with pytest.raises(ReviewValidationError, match="資格情報権限") as captured:
        validate(
            ProviderReviewCandidate(verdict_candidate=ReviewVerdict.PASS, summary="試験"),
            reviewer=reviewer,
        )
    assert captured.value.retryable is False


def test_echoed_head_spoof_is_retryable_provider_error() -> None:
    with pytest.raises(ReviewValidationError, match="異なる先端SHA") as captured:
        validate(
            ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.PASS,
                summary="試験",
                echoed_head_sha="c" * 40,
            )
        )
    assert captured.value.retryable is True


@pytest.mark.parametrize("echoed_head_sha", [None, "", "   "])
def test_missing_or_empty_echoed_head_is_retryable_provider_error(
    echoed_head_sha: str | None,
) -> None:
    item = ProviderReviewCandidate(
        verdict_candidate=ReviewVerdict.PASS,
        summary="問題ありません",
        echoed_head_sha=echoed_head_sha,
    )
    t = target()
    with pytest.raises(ReviewValidationError, match="先端SHAを返しません") as captured:
        validate_candidate(
            item,
            target=t,
            current_head_sha=t.head_sha,
            implementer_identity=identity(
                "implementer", "impl-session", CredentialScope.IMPLEMENTATION_WRITE
            ),
            reviewer_identity=identity(
                "reviewer", "review-session", CredentialScope.REVIEW_WRITE
            ),
            context_complete=True,
        )
    assert captured.value.retryable is True


@pytest.mark.parametrize(
    ("field", "candidate"),
    [
        (
            "要約",
            ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.PASS,
                summary="PASS",
                echoed_head_sha="b" * 40,
            ),
        ),
        (
            "指摘タイトル",
            ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.CHANGES_REQUESTED,
                summary="修正が必要です",
                findings=[blocking().model_copy(update={"title": "bug"})],
                echoed_head_sha="b" * 40,
            ),
        ),
        (
            "指摘根拠",
            ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.CHANGES_REQUESTED,
                summary="修正が必要です",
                findings=[blocking().model_copy(update={"evidence": ["app/a.py:1"]})],
                echoed_head_sha="b" * 40,
            ),
        ),
    ],
)
def test_public_natural_language_requires_japanese(
    field: str, candidate: ProviderReviewCandidate
) -> None:
    with pytest.raises(ReviewValidationError, match=field) as captured:
        validate(candidate)
    assert captured.value.retryable is True


@pytest.mark.parametrize("summary", ["API・schema update", "APIーschema update"])
def test_japanese_punctuation_alone_does_not_satisfy_language_rule(summary: str) -> None:
    candidate = ProviderReviewCandidate(
        verdict_candidate=ReviewVerdict.PASS,
        summary=summary,
        echoed_head_sha="b" * 40,
    )
    with pytest.raises(ReviewValidationError, match="要約"):
        validate(candidate)


def test_stale_current_head_is_not_retryable() -> None:
    item = ProviderReviewCandidate(verdict_candidate=ReviewVerdict.PASS, summary="試験")
    t = target()
    with pytest.raises(ReviewValidationError, match="古く") as captured:
        validate_candidate(
            item,
            target=t,
            current_head_sha="c" * 40,
            implementer_identity=identity(
                "implementer", "impl-session", CredentialScope.IMPLEMENTATION_WRITE
            ),
            reviewer_identity=identity(
                "reviewer", "review-session", CredentialScope.REVIEW_WRITE
            ),
            context_complete=True,
        )
    assert captured.value.retryable is False


def test_excessive_provider_output_is_retryable() -> None:
    candidate = ProviderReviewCandidate(
        verdict_candidate=ReviewVerdict.PASS,
        findings=[],
        summary="あ" * 8_001,
    )
    with pytest.raises(ReviewValidationError, match="安全上限") as captured:
        validate(candidate)
    assert captured.value.retryable is True


def test_aggregate_provider_output_limit_is_retryable() -> None:
    findings = [
        ReviewFinding(
            finding_id=f"F{index}",
            severity=FindingSeverity.INFO,
            category="品質",
            title="確認事項",
            explanation="あ" * 7_000,
            evidence=["根拠があります"],
            fingerprint=f"aggregate:{index}",
        )
        for index in range(2)
    ]
    candidate = ProviderReviewCandidate(
        verdict_candidate=ReviewVerdict.PASS,
        findings=findings,
        summary="確認しました",
        echoed_head_sha="b" * 40,
    )
    with pytest.raises(ReviewValidationError, match="文字数合計") as captured:
        validate(candidate)
    assert captured.value.retryable is True
