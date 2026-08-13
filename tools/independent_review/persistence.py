from __future__ import annotations

from typing import Protocol
import unicodedata

from .models import ReviewDecision

_MARKER = "<!-- yura-independent-ai-review:v1 -->"
_MARKDOWN_SPECIALS = "\\`*_{}[]()#+.!|>"


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


def cycle_key(pr_number: int, head_sha: str, reviewer_agent_id: str) -> str:
    return f"pr:{pr_number}:head:{head_sha}:reviewer:{reviewer_agent_id}"


def render_review_body(decision: ReviewDecision, *, pr_number: int) -> str:
    identity = decision.reviewer_identity
    key = cycle_key(pr_number, decision.reviewed_head_sha, identity.agent_id)
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
            f"  - Evidence: {_safe_review_text('; '.join(item.evidence))}"
        )
    finding_text = "\n".join(findings) if findings else "- none"
    confidence = "n/a" if decision.confidence is None else f"{decision.confidence:.3f}"
    return f"""{_MARKER}
Decision: **{decision.verdict.value}**<br>
Reviewed-Head-SHA: `{decision.reviewed_head_sha}`<br>
Reviewer-Agent: `{identity.agent_id}`<br>
Reviewer-Session: `{identity.session_id}`<br>
Provider: `{identity.provider}`<br>
Model: `{identity.model or 'n/a'}`<br>
Cycle-Key: `{key}`<br>
Confidence: `{confidence}`

### Summary
{_safe_review_text(decision.summary)}

### Findings
{finding_text}
"""


def already_published(writer: ReviewWriter, *, pr_number: int, key: str) -> bool:
    needle = f"Cycle-Key: `{key}`"
    for review in writer.list_reviews(pr_number):
        body = review.get("body")
        if isinstance(body, str) and _MARKER in body and needle in body:
            return True
    return False


def publish_decision(writer: ReviewWriter, *, pr_number: int, decision: ReviewDecision) -> bool:
    key = cycle_key(pr_number, decision.reviewed_head_sha, decision.reviewer_identity.agent_id)
    if already_published(writer, pr_number=pr_number, key=key):
        return False
    writer.create_review_comment(
        pr_number,
        decision.reviewed_head_sha,
        render_review_body(decision, pr_number=pr_number),
    )
    return True
