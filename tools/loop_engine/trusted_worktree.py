"""Codexの編集領域と、信頼済みホストのGit操作を分離する。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .host_runtime import HostTarget, LocalCommandResult, LocalRunner

_REPOSITORY = "ktan514/ai-liver-yura"
_OWNER = "ktan514"
_TRUNK = "rebuild/v2-foundation"
_MISSION_ISSUE = 450


@dataclass(frozen=True, slots=True)
class PreparedWorktree:
    """Codexへ渡す前に信頼済みホストが固定した作業系統。"""

    branch: str
    start_head: str
    pr_number: int | None
    reconciliation_started: bool


@dataclass(frozen=True, slots=True)
class FinalizedWorktree:
    """信頼済みホストがコミット（commit）と送信（push）を完了した作業結果。"""

    branch: str
    head_sha: str
    pr_number: int


class TrustedWorktree:
    """Gitの管理情報（metadata）の変更をCodexから分離し、信頼済みホストだけで実行する。"""

    def __init__(
        self,
        runner: LocalRunner,
        root: Path,
        environment: Mapping[str, str],
    ) -> None:
        self._runner = runner
        self._root = root
        self._environment = _trusted_environment(environment)

    def prepare(self, target: HostTarget) -> PreparedWorktree | None:
        """作業ブランチ（branch）を厳密なHEADへ合わせ、必要なら通常統合（merge）を開始する。"""

        if not self._worktree_is_clean():
            return None

        if target.pr_number is None:
            branch = self._prepare_new_branch(target.work_issue)
            if branch is None:
                return None
            head = self._git_output(("rev-parse", "HEAD"))
            if head is None:
                return None
            return PreparedWorktree(branch, head, None, False)

        if target.head_sha is None:
            return None
        pull = self._api_json(f"repos/{_REPOSITORY}/pulls/{target.pr_number}")
        if pull is None:
            return None
        head = pull.get("head")
        if not isinstance(head, dict):
            return None
        branch = head.get("ref")
        live_head = head.get("sha")
        if not isinstance(branch, str) or not isinstance(live_head, str):
            return None
        if live_head != target.head_sha:
            return None
        if not self._checkout_existing_branch(branch, target.head_sha):
            return None

        reconciliation_started = False
        if _requires_reconciliation(pull):
            reconciliation_started = self._start_trunk_merge()
            if not reconciliation_started:
                return None

        return PreparedWorktree(
            branch,
            target.head_sha,
            target.pr_number,
            reconciliation_started,
        )

    def finalize(
        self,
        target: HostTarget,
        prepared: PreparedWorktree,
        *,
        repair: bool,
    ) -> FinalizedWorktree | None:
        """Codexの作業領域（worktree）の差分を検証し、信頼済みホストでコミット・送信する。"""

        unresolved = self._git_output(("diff", "--name-only", "--diff-filter=U"))
        if unresolved is None or unresolved.strip():
            return None
        if not self._git(("diff", "--check")).succeeded:
            return None
        if not self._git(("add", "-A")).succeeded:
            return None

        staged = self._git(("diff", "--cached", "--quiet"))
        if staged.returncode == 0:
            return None
        if staged.returncode != 1:
            return None

        message = _commit_message(target.work_issue, prepared.reconciliation_started, repair)
        if not self._git(("commit", "-m", message), timeout_seconds=180).succeeded:
            return None
        head_sha = self._git_output(("rev-parse", "HEAD"))
        if head_sha is None or len(head_sha) != 40:
            return None
        if not self._git(
            ("push", "-u", "origin", f"HEAD:{prepared.branch}"),
            timeout_seconds=300,
        ).succeeded:
            return None

        pr_number = prepared.pr_number
        if pr_number is None:
            pr_number = self._create_draft_pr(target.work_issue, prepared.branch)
            if pr_number is None:
                return None

        if not self._publish_checkpoint(
            target.work_issue,
            pr_number,
            prepared.branch,
            head_sha,
        ):
            return None
        return FinalizedWorktree(prepared.branch, head_sha, pr_number)

    def abort_merge_if_needed(self, prepared: PreparedWorktree | None) -> None:
        """Codex失敗時に信頼済みホストが開始した未完了の統合（merge）だけを取り消す。"""

        if prepared is None or not prepared.reconciliation_started:
            return
        self._git(("merge", "--abort"))

    def _prepare_new_branch(self, work_issue: int) -> str | None:
        if not self._git(("fetch", "origin", _TRUNK), timeout_seconds=180).succeeded:
            return None
        if not self._git(("switch", _TRUNK)).succeeded:
            return None
        if not self._git(("merge", "--ff-only", f"origin/{_TRUNK}")).succeeded:
            return None
        branch = f"loop/work-{work_issue}"
        local = self._git(("show-ref", "--verify", "--quiet", f"refs/heads/{branch}"))
        if local.returncode == 0:
            return None
        if local.returncode not in {0, 1}:
            return None
        remote = self._git(("ls-remote", "--exit-code", "--heads", "origin", branch))
        if remote.returncode == 0:
            return None
        if remote.returncode not in {0, 2}:
            return None
        if not self._git(("switch", "-c", branch)).succeeded:
            return None
        return branch

    def _checkout_existing_branch(self, branch: str, expected_head: str) -> bool:
        if not self._git(("fetch", "origin", branch), timeout_seconds=180).succeeded:
            return False
        switched = self._git(("switch", branch))
        if not switched.succeeded:
            switched = self._git(("switch", "--track", "-c", branch, f"origin/{branch}"))
        if not switched.succeeded:
            return False
        if not self._git(("merge", "--ff-only", f"origin/{branch}")).succeeded:
            return False
        current = self._git_output(("rev-parse", "HEAD"))
        return current == expected_head

    def _start_trunk_merge(self) -> bool:
        if not self._git(("fetch", "origin", _TRUNK), timeout_seconds=180).succeeded:
            return False
        result = self._git(("merge", "--no-commit", "--no-ff", f"origin/{_TRUNK}"))
        if result.returncode == 0:
            return True
        if result.returncode != 1:
            return False
        unresolved = self._git_output(("diff", "--name-only", "--diff-filter=U"))
        return unresolved is not None and bool(unresolved.strip())

    def _worktree_is_clean(self) -> bool:
        output = self._git_output(("status", "--porcelain"))
        return output is not None and not output.strip()

    def _create_draft_pr(self, work_issue: int, branch: str) -> int | None:
        title = f"#{work_issue} の実装を進める"
        body = (
            f"Issue #{work_issue} のLoop Engineeringによる自動実装用の下書きPR（Draft PR）。\n\n"
            "設計・実装・検証はRepository正本とAGENTS.mdに従う。"
        )
        created = self._gh(
            (
                "pr",
                "create",
                "--repo",
                _REPOSITORY,
                "--base",
                _TRUNK,
                "--head",
                branch,
                "--draft",
                "--title",
                title,
                "--body",
                body,
            ),
            timeout_seconds=120,
        )
        if not created.succeeded:
            return None
        pulls = self._api_value(
            f"repos/{_REPOSITORY}/pulls?state=open&head={_OWNER}:{branch}&per_page=10"
        )
        if not isinstance(pulls, list) or len(pulls) != 1:
            return None
        item = pulls[0]
        if not isinstance(item, dict):
            return None
        number = item.get("number")
        return number if isinstance(number, int) else None

    def _publish_checkpoint(
        self,
        work_issue: int,
        pr_number: int,
        branch: str,
        head_sha: str,
    ) -> bool:
        body = (
            "## Mission Checkpoint — ACTIVE / 実装更新\n\n"
            "- Mission state: `ACTIVE`\n"
            f"- current Work: #{work_issue}\n"
            f"- current PR: #{pr_number}\n"
            f"- current branch: `{branch}`\n"
            f"- exact HEAD: `{head_sha}`\n"
            "- 完了済み: Codexによるファイル編集と検証後、"
            "信頼済みホストがコミット（commit）と送信（push）を実施\n"
            "- next action: exact HEADのCIを確認し、結果に応じて継続する"
        )
        return self._gh(
            (
                "api",
                f"repos/{_REPOSITORY}/issues/{_MISSION_ISSUE}/comments",
                "-f",
                f"body={body}",
            )
        ).succeeded

    def _api_json(self, endpoint: str) -> dict[str, object] | None:
        value = self._api_value(endpoint)
        if not isinstance(value, dict):
            return None
        return cast(dict[str, object], value)

    def _api_value(self, endpoint: str) -> object | None:
        result = self._gh(("api", endpoint))
        if not result.succeeded:
            return None
        try:
            return json.loads(result.output)
        except json.JSONDecodeError:
            return None

    def _git_output(self, arguments: Sequence[str]) -> str | None:
        result = self._git(arguments)
        if not result.succeeded:
            return None
        return result.output.strip()

    def _git(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: int = 120,
    ) -> LocalCommandResult:
        return self._runner.run(
            ("git", *arguments),
            cwd=self._root,
            environment=self._environment,
            timeout_seconds=timeout_seconds,
        )

    def _gh(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: int = 60,
    ) -> LocalCommandResult:
        return self._runner.run(
            ("gh", *arguments),
            cwd=self._root,
            environment=self._environment,
            timeout_seconds=timeout_seconds,
        )


def _requires_reconciliation(pull: Mapping[str, object]) -> bool:
    return pull.get("mergeable") is False or pull.get("mergeable_state") == "dirty"


def _commit_message(work_issue: int, reconciliation: bool, repair: bool) -> str:
    if reconciliation:
        return f"#{work_issue} を最新基幹へ統合する"
    if repair:
        return f"#{work_issue} の動作不具合を修正する"
    return f"#{work_issue} の実装を進める"


def _trusted_environment(environment: Mapping[str, str]) -> dict[str, str]:
    allowed = {"PATH", "HOME", "GH_TOKEN", "LANG", "LC_ALL", "TMPDIR"}
    return {key: value for key, value in environment.items() if key in allowed}
