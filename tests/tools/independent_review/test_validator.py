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
        base_ref="base",
        base_sha="a" * 40,
        head_ref="head",
        head_sha="b" * 40,
        requested_at=datetime.now(timezone.utc),
    )


def blocking() -> ReviewFinding:
    return ReviewFinding(
        finding_id="F1",
        severity=FindingSeverity.BLOCKING,
        category="correctness",
        title="bug",
        explanation="broken",
        evidence=["line 1"],
        fingerprint="bug:1",
    )


def validate(candidate: ProviderReviewCandidate, *, reviewer: AgentIdentity | None = None):
    t = target()
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
        ProviderReviewCandidate(verdict_candidate=ReviewVerdict.PASS, summary="looks good")
    )
    assert decision.verdict == ReviewVerdict.PASS
    assert decision.blocking_finding_ids == []


def test_pass_with_blocking_is_rejected() -> None:
    with pytest.raises(ReviewValidationError, match="PASS"):
        validate(
            ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.PASS,
                findings=[blocking()],
                summary="wrong",
            )
        )


def test_changes_requested_requires_blocking() -> None:
    with pytest.raises(ReviewValidationError, match="requires"):
        validate(
            ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.CHANGES_REQUESTED,
                summary="change",
            )
        )


def test_agent_collision_is_rejected() -> None:
    reviewer = identity("implementer", "different", CredentialScope.REVIEW_WRITE)
    with pytest.raises(ReviewValidationError, match="agent identity"):
        validate(
            ProviderReviewCandidate(verdict_candidate=ReviewVerdict.PASS, summary="x"),
            reviewer=reviewer,
        )


def test_forbidden_reviewer_scope_is_rejected() -> None:
    reviewer = identity("reviewer", "different", CredentialScope.IMPLEMENTATION_WRITE)
    with pytest.raises(ReviewValidationError, match="credential"):
        validate(
            ProviderReviewCandidate(verdict_candidate=ReviewVerdict.PASS, summary="x"),
            reviewer=reviewer,
        )


def test_echoed_head_spoof_is_rejected() -> None:
    with pytest.raises(ReviewValidationError, match="echoed"):
        validate(
            ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.PASS,
                summary="x",
                echoed_head_sha="c" * 40,
            )
        )
