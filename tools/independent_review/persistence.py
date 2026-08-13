from __future__ import annotations

import unicodedata
from collections.abc import Callable
from typing import Protocol

from .models import ReviewDecision

_MARKER = "<!-- yura-independent-ai-review:v1 -->"
_MARKDOWN_SPECIALS = "\\`*_{}[]()#+.!|>"
_MAX_REVIEW_BODY_CHARS = 60_000


def _safe_review_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(
        char
        if char in {"\n", "\t"} or not unicodedata.category(char).startswith("C")
        else "�"
        for char in normalized
    )
    normalized = normalized.replace("@", "@\u200b")
    normalized = normalized.replace("<", "&lt;").replace(">", "&gt;")
    for char in _MARKDOWN_SPECIALS:
        normalized = normalized.replace(char, "\\" + char)
    return normalized


class ReviewWriter(Protocol):
    def list_reviews(self, pr_number: int) -> list[dict[str, object]]: ...

    def create_review_comment(self, pr_number: int, commit_id: str, body: str) -> None: ...


def cycle_key(
    pr_number: int,
    head_sha: str,
    reviewer_agent_id: str,
    reviewer_session_id: str,
) -> str:
    return (
        f"pr:{pr_number}:head:{head_sha}:reviewer:{reviewer_agent_id}:"
        f"session:{reviewer_session_id}"
    )


def render_review_body(decision: ReviewDecision, *, pr_number: int) -> str:
    identity = decision.reviewer_identity
    key = cycle_key(
        pr_number,
        decision.reviewed_head_sha,
        identity.agent_id,
        identity.session_id,
    )
    findings = []
    for item in decision.findings:
        location = ""
        if item.file_path:
            location = f" ({item.file_path}"
            if item.line_start:
                location += f":{item.line_start}"
            location += ")"
        findings.append(
            f"- **{item.severity.value}** `{_safe_review_text(item.finding_id)}` "
            f"{_safe_review_text(item.title)}{_safe_review_text(location)}\n"
            f"  - {_safe_review_text(item.explanation)}\n"
            f"  - 根拠: {_safe_review_text('; '.join(item.evidence))}\n"
            f"  - fingerprint: {_safe_review_text(item.fingerprint)}"
        )
    finding_text = "\n".join(findings) if findings else "- なし"
    confidence = "なし" if decision.confidence is None else f"{decision.confidence:.3f}"
    body = f"""{_MARKER}
判定: **{decision.verdict.value}**<br>
レビュー対象SHA: `{decision.reviewed_head_sha}`<br>
レビュー担当AI: `{identity.agent_id}`<br>
レビュー実行識別子: `{identity.session_id}`<br>
提供元: `{identity.provider}`<br>
モデル: `{identity.model or 'なし'}`<br>
循環識別子: `{key}`<br>
信頼度: `{confidence}`

### 要約
{_safe_review_text(decision.summary)}

### 指摘
{finding_text}
"""
    if len(body) > _MAX_REVIEW_BODY_CHARS:
        raise ValueError("整形後のレビュー本文が安全上限を超えています")
    return body


def already_published(
    writer: ReviewWriter, *, pr_number: int, key: str, expected_author: str | None
) -> bool:
    needle = f"循環識別子: `{key}`"
    for review in writer.list_reviews(pr_number):
        body = review.get("body")
        user = review.get("user")
        author = user.get("login") if isinstance(user, dict) else None
        if (
            expected_author is not None
            and author == expected_author
            and isinstance(body, str)
            and _MARKER in body
            and needle in body
        ):
            return True
    return False


def publish_decision(
    writer: ReviewWriter,
    *,
    pr_number: int,
    decision: ReviewDecision,
    before_publish: Callable[[], None] | None = None,
) -> bool:
    key = cycle_key(
        pr_number,
        decision.reviewed_head_sha,
        decision.reviewer_identity.agent_id,
        decision.reviewer_identity.session_id,
    )
    duplicate = already_published(
        writer,
        pr_number=pr_number,
        key=key,
        expected_author=decision.reviewer_identity.principal,
    )
    if before_publish is not None:
        before_publish()
    if duplicate:
        return False
    writer.create_review_comment(
        pr_number,
        decision.reviewed_head_sha,
        render_review_body(decision, pr_number=pr_number),
    )
    return True
