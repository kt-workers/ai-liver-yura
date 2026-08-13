from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Protocol

from .models import (
    AgentIdentity,
    AuthorityText,
    EvidenceSource,
    GateEvidence,
    ReviewContext,
    ReviewTarget,
)

_ISSUE_PATTERNS = (
    re.compile(r"(?im)^\s*(?:relates\s+to|closes|fixes|resolves)\s+#(\d+)\b"),
    re.compile(r"(?im)^\s*(?:relates\s+to|closes|fixes|resolves):?\s*#(\d+)\b"),
)
_CANONICAL_PATH = re.compile(r"`(docs/[^`]+\.md)`")


class ContextBuildError(RuntimeError):
    pass


class GitHubReader(Protocol):
    def get_pull(self, pr_number: int) -> dict[str, object]: ...

    def get_pull_diff(self, pr_number: int) -> str: ...

    def get_issue(self, issue_number: int) -> dict[str, object]: ...

    def get_content(self, path: str, ref: str) -> str: ...

    def list_workflow_runs_for_head(self, head_sha: str) -> list[dict[str, object]]: ...


def extract_linked_issue_numbers(pr_body: str) -> list[int]:
    found: list[int] = []
    for pattern in _ISSUE_PATTERNS:
        for match in pattern.finditer(pr_body):
            number = int(match.group(1))
            if number not in found:
                found.append(number)
    return found


def extract_canonical_paths(issue_body: str) -> list[str]:
    marker = re.search(r"(?im)^\s*Canonical:\s*$", issue_body)
    if marker is None:
        return []
    tail = issue_body[marker.end() :]
    block_lines: list[str] = []
    for raw_line in tail.splitlines():
        line = raw_line.strip()
        if not line:
            if block_lines:
                break
            continue
        if line.startswith("##"):
            break
        if not line.startswith("-"):
            break
        block_lines.append(line)
    paths: list[str] = []
    for line in block_lines:
        paths.extend(_CANONICAL_PATH.findall(line))
    return list(dict.fromkeys(paths))


def _as_dict(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ContextBuildError(f"{name} is missing or invalid")
    return value


def _as_str(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContextBuildError(f"{name} is missing or invalid")
    return value


def build_context(
    github: GitHubReader,
    *,
    repository: str,
    pr_number: int,
    implementer_identity: AgentIdentity,
    max_context_chars: int,
) -> ReviewContext:
    pr = github.get_pull(pr_number)
    body = str(pr.get("body") or "")
    issue_numbers = extract_linked_issue_numbers(body)
    if len(issue_numbers) != 1:
        raise ContextBuildError(
            f"expected exactly one linked Work Issue, found {issue_numbers or 'none'}"
        )
    issue_number = issue_numbers[0]
    issue = github.get_issue(issue_number)
    labels_obj = issue.get("labels") or []
    label_names = {
        item.get("name")
        for item in labels_obj
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if "v2" not in label_names:
        raise ContextBuildError(f"linked Issue #{issue_number} is not labeled v2")

    issue_body = str(issue.get("body") or "")
    canonical_paths = extract_canonical_paths(issue_body)
    if not canonical_paths:
        raise ContextBuildError(f"linked Issue #{issue_number} has no Canonical paths")

    base = _as_dict(pr.get("base"), name="PR base")
    head = _as_dict(pr.get("head"), name="PR head")
    base_sha = _as_str(base.get("sha"), name="base SHA")
    head_sha = _as_str(head.get("sha"), name="head SHA")
    target = ReviewTarget(
        repository=repository,
        pr_number=pr_number,
        base_ref=_as_str(base.get("ref"), name="base ref"),
        base_sha=base_sha,
        head_ref=_as_str(head.get("ref"), name="head ref"),
        head_sha=head_sha,
        issue_refs=[issue_number],
        canonical_design_refs=canonical_paths,
        requested_at=datetime.now(timezone.utc),
    )

    canonical_documents = [
        AuthorityText(
            authority="CANONICAL_REQUIREMENT",
            reference=path,
            content=github.get_content(path, base_sha),
        )
        for path in canonical_paths
    ]
    diff = github.get_pull_diff(pr_number)

    gate_evidence: list[GateEvidence] = []
    for run in github.list_workflow_runs_for_head(head_sha):
        conclusion = run.get("conclusion")
        if not isinstance(conclusion, str) or not conclusion:
            continue
        run_head = run.get("head_sha")
        if run_head != head_sha:
            continue
        updated_at_raw = run.get("updated_at")
        try:
            observed_at = datetime.fromisoformat(str(updated_at_raw).replace("Z", "+00:00"))
        except ValueError:
            observed_at = datetime.now(timezone.utc)
        gate_evidence.append(
            GateEvidence(
                source=EvidenceSource.GITHUB_ACTION,
                name=str(run.get("name") or "GitHub Actions"),
                head_sha=head_sha,
                conclusion=conclusion,
                run_id=run.get("id") if isinstance(run.get("id"), int) else None,
                source_url=str(run.get("html_url")) if run.get("html_url") else None,
                observed_at=observed_at,
            )
        )

    context = ReviewContext(
        target=target,
        implementer_identity=implementer_identity,
        pr_title=str(pr.get("title") or ""),
        pr_body=body,
        pr_diff=diff,
        issue_number=issue_number,
        issue_title=str(issue.get("title") or ""),
        issue_body=issue_body,
        canonical_documents=canonical_documents,
        gate_evidence=gate_evidence,
        metadata={"draft": bool(pr.get("draft"))},
    )
    serialized_size = len(context.model_dump_json())
    if serialized_size > max_context_chars:
        raise ContextBuildError(
            f"review context exceeds configured budget: {serialized_size} > {max_context_chars}"
        )
    return context


def render_reviewer_input(context: ReviewContext) -> str:
    canonical = "\n\n".join(
        f"--- {doc.reference} ---\n{doc.content}" for doc in context.canonical_documents
    )
    evidence = "\n".join(
        f"- {item.name}: {item.conclusion} @ {item.head_sha}" for item in context.gate_evidence
    ) or "- none"
    return (
        f"[AUTHORITY: ISSUE_SCOPE]\nIssue #{context.issue_number}: {context.issue_title}\n"
        f"{context.issue_body}\n\n"
        f"[AUTHORITY: CANONICAL_REQUIREMENT]\n{canonical}\n\n"
        f"[TRUSTED FACTS: GATE_EVIDENCE]\n{evidence}\n\n"
        f"[UNTRUSTED: PR_METADATA]\nTitle: {context.pr_title}\n"
        f"Body:\n{context.pr_body}\n\n"
        f"[UNTRUSTED: PR_DIFF]\n{context.pr_diff}\n"
    )
