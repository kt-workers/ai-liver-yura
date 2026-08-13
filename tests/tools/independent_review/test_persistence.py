from __future__ import annotations

from datetime import datetime, timezone

from tools.independent_review.models import (
    AgentIdentity,
    CredentialScope,
    ReviewDecision,
    ReviewVerdict,
)
from tools.independent_review.persistence import publish_decision, render_review_body


class Writer:
    def __init__(self) -> None:
        self.reviews: list[dict[str, object]] = []

    def list_reviews(self, pr_number: int) -> list[dict[str, object]]:
        return self.reviews

    def create_review_comment(self, pr_number: int, commit_id: str, body: str) -> None:
        self.reviews.append({"body": body, "commit_id": commit_id})


def decision() -> ReviewDecision:
    return ReviewDecision(
        verdict=ReviewVerdict.PASS,
        reviewed_head_sha="a" * 40,
        reviewer_identity=AgentIdentity(
            role="REVIEWER",
            provider="google-gemini",
            model="gemini-test",
            agent_id="reviewer",
            session_id="session",
            credential_scope=CredentialScope.REVIEW_WRITE,
        ),
        findings=[],
        blocking_finding_ids=[],
        summary="PASS",
        created_at=datetime.now(timezone.utc),
    )


def test_review_body_contains_machine_marker() -> None:
    body = render_review_body(decision(), pr_number=7)
    assert "yura-independent-ai-review:v1" in body
    assert "Decision: **PASS**" in body
    assert "Reviewed-Head-SHA" in body


def test_duplicate_cycle_is_not_published_twice() -> None:
    writer = Writer()
    item = decision()
    assert publish_decision(writer, pr_number=7, decision=item) is True
    assert publish_decision(writer, pr_number=7, decision=item) is False
    assert len(writer.reviews) == 1


def test_provider_text_is_neutralized_before_markdown_persistence() -> None:
    item = decision()
    malicious = item.model_copy(
        update={
            "summary": "@victim <!-- hidden --> [click](https://example.invalid) \u202ebidi",
        }
    )
    body = render_review_body(malicious, pr_number=7)
    assert "@victim" not in body
    assert "@\u200bvictim" in body
    assert "<!-- hidden -->" not in body
    assert "\\[click\\]" in body
    assert "\u202e" not in body
