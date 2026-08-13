from __future__ import annotations

from tools.independent_review.models import (
    AgentIdentity,
    CredentialScope,
    ProviderReviewCandidate,
    ReviewVerdict,
)
from tools.independent_review.orchestrator import ReviewOrchestrator


class FakeGitHub:
    def __init__(self) -> None:
        self.head = "b" * 40
        self.reviews: list[dict[str, object]] = []

    def get_pull(self, pr_number: int) -> dict[str, object]:
        return {
            "title": "Test PR",
            "body": "Relates to #10",
            "draft": False,
            "base": {"ref": "rebuild/v2-foundation", "sha": "a" * 40},
            "head": {"ref": "feature", "sha": self.head},
        }

    def get_pull_diff(self, pr_number: int) -> str:
        return "+safe change"

    def get_issue(self, issue_number: int) -> dict[str, object]:
        return {
            "title": "Work",
            "body": "Canonical:\n- `docs/a.md`\n\n## Purpose\nTest",
            "labels": [{"name": "v2"}],
        }

    def get_content(self, path: str, ref: str) -> str:
        return "canonical rule"

    def list_workflow_runs_for_head(self, head_sha: str) -> list[dict[str, object]]:
        return []

    def list_reviews(self, pr_number: int) -> list[dict[str, object]]:
        return self.reviews

    def create_review_comment(self, pr_number: int, commit_id: str, body: str) -> None:
        self.reviews.append({"body": body, "commit_id": commit_id})


class FakeBackend:
    provider_name = "fake"
    model_name = "fake"

    def review(self, context):
        return ProviderReviewCandidate(
            verdict_candidate=ReviewVerdict.PASS,
            summary="ok",
            echoed_head_sha=context.target.head_sha,
        )


def test_fake_e2e_pass_and_publish() -> None:
    github = FakeGitHub()
    implementer = AgentIdentity(
        role="IMPLEMENTER",
        provider="github",
        agent_id="impl",
        session_id="impl-session",
        credential_scope=CredentialScope.IMPLEMENTATION_WRITE,
    )
    reviewer = AgentIdentity(
        role="REVIEWER",
        provider="fake",
        agent_id="reviewer",
        session_id="review-session",
        credential_scope=CredentialScope.REVIEW_WRITE,
    )
    orchestrator = ReviewOrchestrator(
        github=github,
        backend=FakeBackend(),
        repository="o/r",
        reviewer_identity=reviewer,
    )
    result = orchestrator.run(pr_number=1, implementer_identity=implementer)
    assert result.decision.verdict == ReviewVerdict.PASS
    assert result.published is True
    assert len(github.reviews) == 1


def test_stale_head_is_not_published() -> None:
    github = FakeGitHub()

    class MutatingBackend(FakeBackend):
        def review(self, context):
            github.head = "c" * 40
            return super().review(context)

    implementer = AgentIdentity(
        role="IMPLEMENTER",
        provider="github",
        agent_id="impl",
        session_id="impl-session",
        credential_scope=CredentialScope.IMPLEMENTATION_WRITE,
    )
    reviewer = AgentIdentity(
        role="REVIEWER",
        provider="fake",
        agent_id="reviewer",
        session_id="review-session",
        credential_scope=CredentialScope.REVIEW_WRITE,
    )
    result = ReviewOrchestrator(
        github=github,
        backend=MutatingBackend(),
        repository="o/r",
        reviewer_identity=reviewer,
    ).run(pr_number=1, implementer_identity=implementer)
    assert result.decision.verdict == ReviewVerdict.BLOCKED
    assert result.published is False
    assert github.reviews == []
