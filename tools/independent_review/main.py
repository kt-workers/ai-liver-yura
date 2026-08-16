from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Protocol

from .context_builder import (
    ContextBuildError,
    validate_pr_scope,
    validate_trusted_base_sha,
)
from .gemini_backend import GeminiReviewerBackend
from .github_client import GitHubApiError, GitHubClient
from .models import AgentIdentity, CredentialScope, ReviewVerdict
from .orchestrator import ReviewOrchestrator

EXIT_PASS = 0
EXIT_CHANGES_REQUESTED = 2
EXIT_BLOCKED = 3
EXIT_INTERNAL_ERROR = 4
STATUS_CONTEXT = "yura/independent-ai-review"
SUPPORTED_BASE_REF = "rebuild/v2-foundation"


class PullReader(Protocol):
    def get_pull(self, pr_number: int) -> dict[str, object]: ...


class StatusWriter(Protocol):
    def create_commit_status(
        self,
        sha: str,
        *,
        state: str,
        context: str,
        description: str,
        target_url: str | None = None,
    ) -> None: ...


def _write_summary(text: str) -> None:
    print(text)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def _exit_for_verdict(verdict: ReviewVerdict) -> int:
    if verdict == ReviewVerdict.PASS:
        return EXIT_PASS
    if verdict == ReviewVerdict.CHANGES_REQUESTED:
        return EXIT_CHANGES_REQUESTED
    return EXIT_BLOCKED


def _status_for_verdict(verdict: ReviewVerdict) -> tuple[str, str]:
    if verdict == ReviewVerdict.PASS:
        return "success", "独立AIレビューに合格しました"
    if verdict == ReviewVerdict.CHANGES_REQUESTED:
        return "failure", "独立AIレビューで修正必須の指摘があります"
    return "error", "独立AIレビューを完了できませんでした"


def _is_supported_target(repository: str, base_full_name: object, base_ref: object) -> bool:
    return base_full_name == repository and base_ref == SUPPORTED_BASE_REF


def _workflow_run_url(repository: str) -> str | None:
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.getenv("GITHUB_RUN_ID")
    if not run_id:
        return None
    return f"{server}/{repository}/actions/runs/{run_id}"


def _integer_setting(name: str, default: str) -> int:
    raw = os.getenv(name, default)
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name}の形式が不正です") from exc


def _live_target_matches(
    client: PullReader,
    *,
    repository: str,
    pr_number: int,
    expected_head_sha: str,
) -> bool:
    try:
        validate_pr_scope(
            client.get_pull(pr_number),
            repository=repository,
            expected_head_sha=expected_head_sha,
        )
    except ContextBuildError:
        return False
    return True


def _set_status(
    client: StatusWriter,
    head_sha: str,
    *,
    state: str,
    description: str,
    target_url: str | None,
) -> bool:
    try:
        client.create_commit_status(
            head_sha,
            state=state,
            context=STATUS_CONTEXT,
            description=description,
            target_url=target_url,
        )
        return True
    except GitHubApiError as exc:
        _write_summary(f"独立AIレビューの状態書込に失敗しました: {exc}")
        return False


def main() -> int:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    repository = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")
    if not event_path or not repository or not token:
        _write_summary("独立AIレビューに必要なGitHub実行環境情報が不足しています")
        return EXIT_INTERNAL_ERROR

    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr_event = event.get("pull_request")
    if not isinstance(pr_event, dict):
        _write_summary("GitHubイベントにPull Request情報がありません")
        return EXIT_INTERNAL_ERROR
    pr_number = pr_event.get("number")
    if not isinstance(pr_number, int):
        _write_summary("PR番号を取得できません")
        return EXIT_INTERNAL_ERROR
    if bool(pr_event.get("draft")):
        _write_summary("下書きPRのため、レビュー可能状態になるまで独立AIレビューを保留します")
        return EXIT_PASS

    base = pr_event.get("base")
    head = pr_event.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_full_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    base_ref = base.get("ref") if isinstance(base, dict) else None
    head_full_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    head_sha = head.get("sha") if isinstance(head, dict) else None
    if not _is_supported_target(repository, base_full_name, base_ref) or not isinstance(
        head_sha, str
    ):
        _write_summary("PRの対象がV2独立レビューの許可範囲外です")
        return EXIT_BLOCKED
    if head_full_name != repository:
        _write_summary("外部リポジトリ由来PRは現在の安全方針ではレビュー不能として停止します")
        return EXIT_BLOCKED

    labels = pr_event.get("labels") or []
    label_names = {
        item.get("name")
        for item in labels
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if "v2" not in label_names:
        _write_summary("V2対象PRに必須の `v2` ラベルがありません")
        return EXIT_BLOCKED

    user = pr_event.get("user")
    author = user.get("login") if isinstance(user, dict) else None
    if not isinstance(author, str):
        _write_summary("PR作成者情報が不足しています")
        return EXIT_BLOCKED

    trusted_base_raw = os.getenv("YURA_TRUSTED_BASE_SHA")
    if not trusted_base_raw:
        _write_summary("信頼済みV2基準SHAが制御系から渡されていません")
        return EXIT_BLOCKED
    try:
        trusted_base_sha = validate_trusted_base_sha(trusted_base_raw)
    except ContextBuildError as exc:
        _write_summary(f"信頼済みV2基準SHAを採用できません: {exc}")
        return EXIT_BLOCKED

    try:
        trusted_workflow_ids = frozenset(
            int(value.strip())
            for value in os.getenv("YURA_TRUSTED_WORKFLOW_IDS", "").split(",")
            if value.strip()
        )
        max_context_chars = _integer_setting("YURA_REVIEW_MAX_CONTEXT_CHARS", "600000")
        max_backend_attempts = _integer_setting("YURA_REVIEW_MAX_BACKEND_ATTEMPTS", "2")
    except ValueError:
        _write_summary("独立AIレビューの数値設定または信頼済みworkflow IDの形式が不正です")
        return EXIT_BLOCKED

    client = GitHubClient(repository, token, os.getenv("GITHUB_API_URL", "https://api.github.com"))
    run_url = _workflow_run_url(repository)
    try:
        if not _live_target_matches(
            client,
            repository=repository,
            pr_number=pr_number,
            expected_head_sha=head_sha,
        ):
            _write_summary("実レビュー開始前にPRの対象範囲が変化したため実行を停止します")
            return EXIT_BLOCKED
    except GitHubApiError as exc:
        _write_summary(f"PR対象範囲の事前確認中にレビュー不能となりました: {exc}")
        return EXIT_BLOCKED

    if not _set_status(
        client,
        head_sha,
        state="pending",
        description="独立AIレビューを実行しています",
        target_url=run_url,
    ):
        return EXIT_INTERNAL_ERROR

    model = os.getenv("GEMINI_REVIEW_MODEL", "gemini-3.6-flash")
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    implementer = AgentIdentity(
        role="IMPLEMENTER",
        provider="github",
        agent_id=f"github-pr-author:{author}",
        session_id=f"implementation-lineage:{pr_number}:{head_sha}",
        principal=author,
        credential_scope=CredentialScope.IMPLEMENTATION_WRITE,
    )
    reviewer = AgentIdentity(
        role="REVIEWER",
        provider="google-gemini",
        model=model,
        agent_id="yura-independent-reviewer-gemini",
        session_id=f"github-actions:{run_id}:{run_attempt}:{head_sha}",
        principal="github-actions[bot]",
        credential_scope=CredentialScope.REVIEW_WRITE,
    )

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        _set_status(
            client,
            head_sha,
            state="error",
            description="GEMINI_API_KEY が設定されていません",
            target_url=run_url,
        )
        _write_summary("`GEMINI_API_KEY` が未設定のため実レビューを開始できません")
        return EXIT_BLOCKED

    orchestrator = ReviewOrchestrator(
        github=client,
        backend=GeminiReviewerBackend(api_key=api_key, model=model),
        repository=repository,
        reviewer_identity=reviewer,
        max_context_chars=max_context_chars,
        max_backend_attempts=max_backend_attempts,
        trusted_workflow_ids=trusted_workflow_ids,
    )
    try:
        result = orchestrator.run(
            pr_number=pr_number,
            implementer_identity=implementer,
            expected_head_sha=head_sha,
            trusted_base_sha=trusted_base_sha,
        )
    except (ContextBuildError, GitHubApiError) as exc:
        _set_status(
            client,
            head_sha,
            state="error",
            description=f"レビュー不能: {type(exc).__name__}",
            target_url=run_url,
        )
        _write_summary(f"独立AIレビューを完了できませんでした: {type(exc).__name__}: {exc}")
        return EXIT_BLOCKED
    except Exception as exc:
        _set_status(
            client,
            head_sha,
            state="error",
            description=f"レビュー基盤内部エラー: {type(exc).__name__}",
            target_url=run_url,
        )
        _write_summary(f"独立AIレビュー基盤で内部エラーが発生しました: {type(exc).__name__}")
        return EXIT_INTERNAL_ERROR

    try:
        current_target = _live_target_matches(
            client,
            repository=repository,
            pr_number=pr_number,
            expected_head_sha=head_sha,
        )
    except GitHubApiError:
        current_target = False
    if not current_target or result.decision.reviewed_head_sha != head_sha:
        _set_status(
            client,
            head_sha,
            state="error",
            description="レビュー対象が実行開始時から変化しました",
            target_url=run_url,
        )
        _write_summary("レビュー対象の変化を検出したため、最終状態を採用しません")
        return EXIT_BLOCKED

    try:
        orchestrator.assert_authority_generation_current(
            expected_authority_generation=result.authority_generation,
            pr_number=pr_number,
            implementer_identity=implementer,
            expected_head_sha=head_sha,
            trusted_base_sha=trusted_base_sha,
        )
    except (ContextBuildError, GitHubApiError) as exc:
        _set_status(
            client,
            head_sha,
            state="error",
            description="最終状態の正本世代が変化しました",
            target_url=run_url,
        )
        _write_summary(f"最終状態の正本世代確認に失敗しました: {type(exc).__name__}")
        return EXIT_BLOCKED

    state, description = _status_for_verdict(result.decision.verdict)
    if not _set_status(
        client,
        head_sha,
        state=state,
        description=description,
        target_url=run_url,
    ):
        return EXIT_INTERNAL_ERROR
    _write_summary(
        f"独立AIレビュー結果: {result.decision.verdict.value} / "
        f"対象SHA {result.decision.reviewed_head_sha} / 記録済み={result.published}"
    )
    return _exit_for_verdict(result.decision.verdict)


if __name__ == "__main__":
    sys.exit(main())
