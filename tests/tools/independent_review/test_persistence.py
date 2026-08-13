from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tools.independent_review.models import (
    AgentIdentity,
    CredentialScope,
    FindingSeverity,
    ReviewDecision,
    ReviewFinding,
    ReviewVerdict,
)
from tools.independent_review.persistence import publish_decision, render_review_body


class Writer:
    def __init__(self) -> None:
        self.reviews: list[dict[str, object]] = []

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


def decision(
    *, session_id: str = "session", verdict: ReviewVerdict = ReviewVerdict.PASS
) -> ReviewDecision:
    return ReviewDecision(
        verdict=verdict,
        reviewed_head_sha="a" * 40,
        reviewer_identity=AgentIdentity(
            role="REVIEWER",
            provider="google-gemini",
            model="gemini-test",
            agent_id="reviewer",
            session_id=session_id,
            principal="github-actions[bot]",
            credential_scope=CredentialScope.REVIEW_WRITE,
        ),
        findings=[],
        blocking_finding_ids=[],
        summary="問題ありません" if verdict == ReviewVerdict.PASS else "一時的にレビュー不能です",
        created_at=datetime.now(timezone.utc),
    )


def test_review_body_contains_machine_marker() -> None:
    body = render_review_body(decision(), pr_number=7)
    assert "yura-independent-ai-review:v1" in body
    assert "判定: **PASS**" in body
    assert "レビュー対象SHA" in body


def test_duplicate_same_session_is_not_published_twice() -> None:
    writer = Writer()
    item = decision()
    assert publish_decision(writer, pr_number=7, decision=item) is True
    assert publish_decision(writer, pr_number=7, decision=item) is False
    assert len(writer.reviews) == 1


def test_duplicate_path_still_runs_final_authority_check() -> None:
    writer = Writer()
    item = decision()
    assert publish_decision(writer, pr_number=7, decision=item) is True
    checks: list[str] = []
    assert (
        publish_decision(
            writer,
            pr_number=7,
            decision=item,
            before_publish=lambda: checks.append("最終確認"),
        )
        is False
    )
    assert checks == ["最終確認"]


def test_duplicate_marker_from_untrusted_author_does_not_suppress_publish() -> None:
    writer = Writer()
    item = decision()
    forged_body = render_review_body(item, pr_number=7)
    writer.reviews.append(
        {
            "body": forged_body,
            "commit_id": item.reviewed_head_sha,
            "user": {"login": "attacker"},
        }
    )
    assert publish_decision(writer, pr_number=7, decision=item) is True
    assert len(writer.reviews) == 2


def test_final_scope_check_runs_after_duplicate_lookup_before_publish() -> None:
    events: list[str] = []

    class OrderedWriter(Writer):
        def list_reviews(self, pr_number: int) -> list[dict[str, object]]:
            events.append("重複確認")
            return super().list_reviews(pr_number)

        def create_review_comment(
            self, pr_number: int, commit_id: str, body: str
        ) -> None:
            events.append("公開")
            super().create_review_comment(pr_number, commit_id, body)

    ordered = OrderedWriter()
    assert publish_decision(
        ordered,
        pr_number=7,
        decision=decision(),
        before_publish=lambda: events.append("最終確認"),
    )
    assert events == ["重複確認", "最終確認", "公開"]


def test_new_session_on_same_head_is_recorded_as_new_cycle() -> None:
    writer = Writer()
    blocked = decision(session_id="session-1", verdict=ReviewVerdict.BLOCKED)
    passed = decision(session_id="session-2", verdict=ReviewVerdict.PASS)
    assert publish_decision(writer, pr_number=7, decision=blocked) is True
    assert publish_decision(writer, pr_number=7, decision=passed) is True
    assert len(writer.reviews) == 2
    assert "判定: **BLOCKED**" in str(writer.reviews[0]["body"])
    assert "判定: **PASS**" in str(writer.reviews[1]["body"])


def test_provider_text_is_neutralized_before_markdown_persistence() -> None:
    item = decision()
    malicious = item.model_copy(
        update={
            "summary": "@victim <!-- hidden --> [リンク](https://example.invalid) \u202e逆方向",
        }
    )
    body = render_review_body(malicious, pr_number=7)
    assert "@victim" not in body
    assert "@\u200bvictim" in body
    assert "<!-- hidden -->" not in body
    assert "\\[リンク\\]" in body
    assert "\u202e" not in body


def test_finding_fingerprint_is_persisted_in_audit_body() -> None:
    item = decision().model_copy(
        update={
            "findings": [
                ReviewFinding(
                    finding_id="F1",
                    severity=FindingSeverity.HIGH,
                    category="correctness",
                    title="契約違反",
                    explanation="契約と一致しません",
                    evidence=["対象行を確認しました"],
                    fingerprint="contract:result@v1",
                )
            ]
        }
    )
    body = render_review_body(item, pr_number=7)
    assert "fingerprint: contract:result@\u200bv1" in body


def test_formatted_review_body_has_final_size_limit() -> None:
    item = decision().model_copy(update={"summary": "<" * 16_000})
    with pytest.raises(ValueError, match="整形後"):
        render_review_body(item, pr_number=7)
