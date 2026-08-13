from __future__ import annotations

import pytest

from tools.independent_review.context_builder import ContextBuildError
from tools.independent_review.models import (
    AgentIdentity,
    CredentialScope,
    FindingSeverity,
    ProviderReviewCandidate,
    ReviewFinding,
    ReviewVerdict,
)
from tools.independent_review.orchestrator import ReviewOrchestrator


class FakeGitHub:
    def __init__(self) -> None:
        self.repository = "o/r"
        self.head = "b" * 40
        self.base_ref = "rebuild/v2-foundation"
        self.draft = False
        self.labels = [{"name": "v2"}]
        self.reviews: list[dict[str, object]] = []
        self.content_refs: list[str] = []
        self.issue_body = "正本:\n- `docs/a.md`\n\n## 目的\n試験"

    def get_pull(self, pr_number: int) -> dict[str, object]:
        return {
            "title": "試験PR",
            "body": "関連Issue: #10",
            "draft": self.draft,
            "labels": self.labels,
            "base": {
                "ref": self.base_ref,
                "sha": "a" * 40,
                "repo": {"full_name": self.repository},
            },
            "head": {
                "ref": "feature",
                "sha": self.head,
                "repo": {"full_name": self.repository},
            },
        }

    def get_pull_diff(self, pr_number: int) -> str:
        return "+安全な変更"

    def get_issue(self, issue_number: int) -> dict[str, object]:
        return {
            "title": "作業Issue",
            "body": self.issue_body,
            "labels": [{"name": "v2"}],
        }

    def get_content(self, path: str, ref: str) -> str:
        self.content_refs.append(ref)
        return "正本規則"

    def list_workflow_runs_for_head(self, head_sha: str) -> list[dict[str, object]]:
        return []

    def list_reviews(self, pr_number: int) -> list[dict[str, object]]:
        return self.reviews

    def create_review_comment(self, pr_number: int, commit_id: str, body: str) -> None:
        self.reviews.append(
            {
                "body": body,
                "commit_id": commit_id,
                "user": {"login": "github-actions[bot]"},
            }
        )


class FakeBackend:
    provider_name = "fake"
    model_name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def review(self, context):
        self.calls += 1
        return ProviderReviewCandidate(
            verdict_candidate=ReviewVerdict.PASS,
            summary="問題ありません",
            echoed_head_sha=context.target.head_sha,
        )


def _implementer() -> AgentIdentity:
    return AgentIdentity(
        role="IMPLEMENTER",
        provider="github",
        agent_id="impl",
        session_id="impl-session",
        credential_scope=CredentialScope.IMPLEMENTATION_WRITE,
    )


def _reviewer() -> AgentIdentity:
    return AgentIdentity(
        role="REVIEWER",
        provider="fake",
        agent_id="reviewer",
        session_id="review-session",
        credential_scope=CredentialScope.REVIEW_WRITE,
    )


def _run(github: FakeGitHub, backend: FakeBackend):
    return ReviewOrchestrator(
        github=github,
        backend=backend,
        repository=github.repository,
        reviewer_identity=_reviewer(),
        max_backend_attempts=2,
    ).run(
        pr_number=1,
        implementer_identity=_implementer(),
        expected_head_sha=github.head,
        trusted_base_sha="d" * 40,
    )


def test_fake_e2e_pass_and_publish() -> None:
    github = FakeGitHub()
    backend = FakeBackend()
    result = _run(github, backend)
    assert result.decision.verdict == ReviewVerdict.PASS
    assert result.published is True
    assert backend.calls == 1
    assert len(github.reviews) == 1
    assert github.content_refs == ["d" * 40, "d" * 40, "d" * 40]


def test_head_change_before_context_build_is_rejected() -> None:
    github = FakeGitHub()
    expected = "a" * 40
    with pytest.raises(ContextBuildError, match="先端SHA"):
        ReviewOrchestrator(
            github=github,
            backend=FakeBackend(),
            repository=github.repository,
            reviewer_identity=_reviewer(),
        ).run(
            pr_number=1,
            implementer_identity=_implementer(),
            expected_head_sha=expected,
            trusted_base_sha="d" * 40,
        )
    assert github.reviews == []


def test_head_change_during_review_is_not_published() -> None:
    github = FakeGitHub()
    expected = github.head

    class MutatingBackend(FakeBackend):
        def review(self, context):
            self.calls += 1
            github.head = "c" * 40
            return ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.PASS,
                summary="問題ありません",
                echoed_head_sha=context.target.head_sha,
            )

    with pytest.raises(ContextBuildError, match="先端SHA"):
        ReviewOrchestrator(
            github=github,
            backend=MutatingBackend(),
            repository=github.repository,
            reviewer_identity=_reviewer(),
        ).run(
            pr_number=1,
            implementer_identity=_implementer(),
            expected_head_sha=expected,
            trusted_base_sha="d" * 40,
        )
    assert github.reviews == []


def test_scope_change_before_backend_call_is_rejected() -> None:
    class ScopeMutatingGitHub(FakeGitHub):
        def __init__(self) -> None:
            super().__init__()
            self.pull_reads = 0

        def get_pull(self, pr_number: int) -> dict[str, object]:
            self.pull_reads += 1
            if self.pull_reads >= 2:
                self.labels = []
            return super().get_pull(pr_number)

    changed = ScopeMutatingGitHub()
    backend = FakeBackend()
    with pytest.raises(ContextBuildError, match="v2"):
        _run(changed, backend)
    assert backend.calls == 0


def test_retryable_semantic_error_is_retried() -> None:
    github = FakeGitHub()

    class RetryBackend(FakeBackend):
        def review(self, context):
            self.calls += 1
            if self.calls == 1:
                return ProviderReviewCandidate(
                    verdict_candidate=ReviewVerdict.PASS,
                    findings=[
                        ReviewFinding(
                            finding_id="F1",
                            severity=FindingSeverity.BLOCKING,
                            category="correctness",
                            title="不具合",
                            explanation="契約違反",
                            evidence=["根拠"],
                            fingerprint="f1",
                        )
                    ],
                    summary="不整合な候補",
                    echoed_head_sha=context.target.head_sha,
                )
            return ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.PASS,
                summary="再生成で整合しました",
                echoed_head_sha=context.target.head_sha,
            )

    backend = RetryBackend()
    result = _run(github, backend)
    assert backend.calls == 2
    assert result.decision.verdict == ReviewVerdict.PASS
    assert result.published is True


def test_retry_exhaustion_becomes_blocked() -> None:
    github = FakeGitHub()

    class InvalidBackend(FakeBackend):
        def review(self, context):
            self.calls += 1
            return ProviderReviewCandidate(
                verdict_candidate=ReviewVerdict.CHANGES_REQUESTED,
                findings=[],
                summary="指摘不足",
                echoed_head_sha=context.target.head_sha,
            )

    backend = InvalidBackend()
    result = _run(github, backend)
    assert backend.calls == 2
    assert result.decision.verdict == ReviewVerdict.BLOCKED
    assert result.published is True


def test_authority_generation_change_before_publish_is_not_published() -> None:
    github = FakeGitHub()

    class AuthorityMutatingBackend(FakeBackend):
        def review(self, context):
            candidate = super().review(context)
            github.issue_body += "\n\n## 追加要件\n公開前に変更"
            return candidate

    result = _run(github, AuthorityMutatingBackend())
    assert result.decision.verdict == ReviewVerdict.BLOCKED
    assert result.published is False
    assert github.reviews == []


def test_head_change_during_duplicate_lookup_is_not_published() -> None:
    class LookupMutatingGitHub(FakeGitHub):
        def list_reviews(self, pr_number: int) -> list[dict[str, object]]:
            self.head = "c" * 40
            return super().list_reviews(pr_number)

    github = LookupMutatingGitHub()
    with pytest.raises(ContextBuildError, match="先端SHA"):
        _run(github, FakeBackend())
    assert github.reviews == []


def test_authority_change_during_duplicate_lookup_is_not_published() -> None:
    class LookupMutatingGitHub(FakeGitHub):
        def list_reviews(self, pr_number: int) -> list[dict[str, object]]:
            self.issue_body += "\n\n## 変更\n公開直前に変更"
            return super().list_reviews(pr_number)

    github = LookupMutatingGitHub()
    with pytest.raises(ContextBuildError, match="正本世代"):
        _run(github, FakeBackend())
    assert github.reviews == []
