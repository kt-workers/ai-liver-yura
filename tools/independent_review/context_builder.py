from __future__ import annotations

import hashlib
import json
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

_ISSUE_LINE_PATTERN = re.compile(
    r"(?im)^\s*(?:関連Issue|対象Issue|解決|修正|対応)(?:\s*:\s*|\s+)([^\r\n]*)$"
)
_ISSUE_NUMBER_PATTERN = re.compile(r"#(\d+)\b")
_CANONICAL_PATH = re.compile(r"`(docs/[^`]+\.md)`")
_CANONICAL_MARKER = re.compile(r"(?im)^\s*正本:\s*$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SUPPORTED_BASE_REF = "rebuild/v2-foundation"
_WORKFLOW_PATH_PREFIX = ".github/workflows/"


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
    for line_match in _ISSUE_LINE_PATTERN.finditer(pr_body):
        for raw_number in _ISSUE_NUMBER_PATTERN.findall(line_match.group(1)):
            number = int(raw_number)
            if number not in found:
                found.append(number)
    return found


def extract_canonical_paths(issue_body: str) -> list[str]:
    marker = _CANONICAL_MARKER.search(issue_body)
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
        raise ContextBuildError(f"{name} が存在しないか形式が不正です")
    return value


def _as_str(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContextBuildError(f"{name} が存在しないか形式が不正です")
    return value


def _repository_name(value: object, *, name: str) -> str:
    repository = _as_dict(value, name=name)
    return _as_str(repository.get("full_name"), name=f"{name}のリポジトリ名")


def _label_names(value: object) -> set[str]:
    if not isinstance(value, list):
        raise ContextBuildError("ラベル情報の形式が不正です")
    return {
        name
        for item in value
        if isinstance(item, dict)
        for name in [item.get("name")]
        if isinstance(name, str)
    }


def validate_pr_scope(
    pr: dict[str, object],
    *,
    repository: str,
    expected_head_sha: str,
) -> None:
    base = _as_dict(pr.get("base"), name="PR基準情報")
    head = _as_dict(pr.get("head"), name="PR先端情報")

    if bool(pr.get("draft")):
        raise ContextBuildError("PRが下書きへ変更されたためレビューを停止します")
    if _as_str(base.get("ref"), name="基準参照") != _SUPPORTED_BASE_REF:
        raise ContextBuildError("PRの基準ブランチがV2レビュー対象から外れています")
    if _repository_name(base.get("repo"), name="基準リポジトリ") != repository:
        raise ContextBuildError("PRの基準リポジトリがV2レビュー対象から外れています")
    if _repository_name(head.get("repo"), name="先端リポジトリ") != repository:
        raise ContextBuildError("外部リポジトリ由来PRは現在の安全方針ではレビューできません")
    if _as_str(head.get("sha"), name="先端SHA") != expected_head_sha:
        raise ContextBuildError(
            "PR先端SHAが実行開始時から変化しました。古い実行として停止します"
        )

    label_names = _label_names(pr.get("labels") or [])
    if "v2" not in label_names:
        raise ContextBuildError("PRから必須の `v2` ラベルが外れています")


def validate_trusted_base_sha(value: str) -> str:
    if _COMMIT_SHA.fullmatch(value) is None:
        raise ContextBuildError("信頼済みV2基準SHAの形式が不正です")
    return value


def _authority_generation(
    *,
    trusted_base_sha: str,
    relationship_base_sha: str,
    head_sha: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    canonical_documents: list[AuthorityText],
    gate_evidence: list[GateEvidence],
) -> str:
    evidence = sorted(
        (
            item.model_dump(mode="json", exclude_none=False)
            for item in gate_evidence
        ),
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
    )
    payload = {
        "trusted_base_sha": trusted_base_sha,
        "relationship_base_sha": relationship_base_sha,
        "head_sha": head_sha,
        "issue_number": issue_number,
        "issue_title": issue_title,
        "issue_body": issue_body,
        "canonical_documents": [
            item.model_dump(mode="json") for item in canonical_documents
        ],
        "gate_evidence": evidence,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_trusted_workflow_run(
    github: GitHubReader,
    run: dict[str, object],
    *,
    repository: str,
    expected_head_sha: str,
    trusted_base_sha: str,
    trusted_workflow_ids: frozenset[int],
) -> bool:
    """PR側で改変されたworkflowの実行を信頼済み証拠から除外する。"""
    workflow_id = run.get("workflow_id")
    workflow_path = run.get("path")
    if (
        not isinstance(workflow_id, int)
        or workflow_id not in trusted_workflow_ids
        or not isinstance(workflow_path, str)
        or not workflow_path.startswith(_WORKFLOW_PATH_PREFIX)
        or run.get("head_sha") != expected_head_sha
        or run.get("event") != "pull_request"
    ):
        return False
    head_repository = run.get("head_repository")
    if not isinstance(head_repository, dict) or head_repository.get("full_name") != repository:
        return False
    try:
        trusted_definition = github.get_content(workflow_path, trusted_base_sha)
        reviewed_definition = github.get_content(workflow_path, expected_head_sha)
    except Exception as error:
        raise ContextBuildError("信頼済みworkflow定義を確認できません") from error
    return trusted_definition == reviewed_definition


def build_context(
    github: GitHubReader,
    *,
    repository: str,
    pr_number: int,
    implementer_identity: AgentIdentity,
    expected_head_sha: str,
    trusted_base_sha: str,
    max_context_chars: int,
    trusted_workflow_ids: frozenset[int] = frozenset(),
) -> ReviewContext:
    trusted_base_sha = validate_trusted_base_sha(trusted_base_sha)
    pr = github.get_pull(pr_number)
    validate_pr_scope(pr, repository=repository, expected_head_sha=expected_head_sha)

    body = str(pr.get("body") or "")
    issue_numbers = extract_linked_issue_numbers(body)
    if len(issue_numbers) != 1:
        found = issue_numbers if issue_numbers else "なし"
        raise ContextBuildError(f"関連する作業Issueは1件だけ必要です。検出結果: {found}")
    issue_number = issue_numbers[0]
    issue = github.get_issue(issue_number)
    if "pull_request" in issue:
        raise ContextBuildError(f"関連番号 #{issue_number} は作業IssueではなくPRです")
    label_names = _label_names(issue.get("labels") or [])
    if "v2" not in label_names:
        raise ContextBuildError(f"関連Issue #{issue_number} に `v2` ラベルがありません")

    issue_body = str(issue.get("body") or "")
    canonical_paths = extract_canonical_paths(issue_body)
    if not canonical_paths:
        raise ContextBuildError(f"関連Issue #{issue_number} に正本文書が指定されていません")

    base = _as_dict(pr.get("base"), name="PR基準情報")
    head = _as_dict(pr.get("head"), name="PR先端情報")
    relationship_base_sha = _as_str(base.get("sha"), name="PR関係基準SHA")
    target = ReviewTarget(
        repository=repository,
        pr_number=pr_number,
        base_ref=_as_str(base.get("ref"), name="基準参照"),
        base_sha=relationship_base_sha,
        trusted_base_sha=trusted_base_sha,
        head_ref=_as_str(head.get("ref"), name="先端参照"),
        head_sha=expected_head_sha,
        issue_refs=[issue_number],
        canonical_design_refs=canonical_paths,
        requested_at=datetime.now(timezone.utc),
    )

    canonical_documents = [
        AuthorityText(
            authority="CANONICAL_REQUIREMENT",
            reference=path,
            content=github.get_content(path, trusted_base_sha),
        )
        for path in canonical_paths
    ]
    diff = github.get_pull_diff(pr_number)

    gate_evidence: list[GateEvidence] = []
    for run in github.list_workflow_runs_for_head(expected_head_sha):
        if not _is_trusted_workflow_run(
            github,
            run,
            repository=repository,
            expected_head_sha=expected_head_sha,
            trusted_base_sha=trusted_base_sha,
            trusted_workflow_ids=trusted_workflow_ids,
        ):
            continue
        run_name = run.get("name")
        if not isinstance(run_name, str):
            continue
        conclusion = run.get("conclusion")
        if not isinstance(conclusion, str) or not conclusion:
            continue
        updated_at_raw = run.get("updated_at")
        try:
            observed_at = datetime.fromisoformat(str(updated_at_raw).replace("Z", "+00:00"))
        except ValueError:
            observed_at = datetime.now(timezone.utc)
        raw_run_id = run.get("id")
        run_id = raw_run_id if isinstance(raw_run_id, int) else None
        gate_evidence.append(
            GateEvidence(
                source=EvidenceSource.GITHUB_ACTION,
                name=run_name,
                head_sha=expected_head_sha,
                conclusion=conclusion,
                run_id=run_id,
                source_url=str(run.get("html_url")) if run.get("html_url") else None,
                observed_at=observed_at,
            )
        )

    issue_title = str(issue.get("title") or "")
    authority_generation = _authority_generation(
        trusted_base_sha=trusted_base_sha,
        relationship_base_sha=relationship_base_sha,
        head_sha=expected_head_sha,
        issue_number=issue_number,
        issue_title=issue_title,
        issue_body=issue_body,
        canonical_documents=canonical_documents,
        gate_evidence=gate_evidence,
    )
    context = ReviewContext(
        target=target,
        implementer_identity=implementer_identity,
        pr_title=str(pr.get("title") or ""),
        pr_body=body,
        pr_diff=diff,
        issue_number=issue_number,
        issue_title=issue_title,
        issue_body=issue_body,
        canonical_documents=canonical_documents,
        gate_evidence=gate_evidence,
        authority_generation=authority_generation,
        metadata={"draft": bool(pr.get("draft"))},
    )
    serialized_size = len(context.model_dump_json())
    if serialized_size > max_context_chars:
        raise ContextBuildError(
            f"レビュー入力が上限を超えました: {serialized_size} > {max_context_chars}"
        )
    return context


def render_reviewer_input(context: ReviewContext) -> str:
    target = context.target
    review_target = (
        f"リポジトリ: {target.repository}\n"
        f"PR: {target.pr_number}\n"
        f"基準参照: {target.base_ref}\n"
        f"PR関係基準SHA: {target.base_sha}\n"
        f"正本基準SHA: {target.trusted_base_sha}\n"
        f"先端参照: {target.head_ref}\n"
        f"レビュー対象SHA: {target.head_sha}"
    )
    canonical = "\n\n".join(
        f"--- {doc.reference} ---\n{doc.content}" for doc in context.canonical_documents
    )
    evidence = "\n".join(
        f"- {item.name}: {item.conclusion} @ {item.head_sha}" for item in context.gate_evidence
    ) or "- なし"
    return (
        f"[信頼済み事実: レビュー対象]\n{review_target}\n\n"
        f"[権限情報: Issue責務]\nIssue #{context.issue_number}: {context.issue_title}\n"
        f"{context.issue_body}\n\n"
        f"[権限情報: 正本要件]\n{canonical}\n\n"
        f"[信頼済み事実: 検証証拠]\n{evidence}\n\n"
        f"[信頼できないデータ: PRメタデータ]\nタイトル: {context.pr_title}\n"
        f"本文:\n{context.pr_body}\n\n"
        f"[信頼できないデータ: PR差分]\n{context.pr_diff}\n"
    )
