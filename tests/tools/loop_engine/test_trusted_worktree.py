from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from tools.loop_engine.host_runtime import HostTarget, LocalCommandResult
from tools.loop_engine.trusted_worktree import TrustedWorktree


class ScriptedRunner:
    def __init__(self, responses: Mapping[tuple[str, ...], LocalCommandResult]) -> None:
        self._responses = dict(responses)
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: int = 120,
        capture_output: bool = True,
    ) -> LocalCommandResult:
        del cwd, environment, timeout_seconds, capture_output
        args = tuple(command)
        self.commands.append(args)
        response = self._responses.get(args)
        if response is None:
            raise AssertionError(f"想定外のコマンドです: {args}")
        return response


def test_existing_pr_is_prepared_without_codex_git_write() -> None:
    head = "a" * 40
    pull = {
        "head": {"ref": "feature/work", "sha": head},
        "mergeable": True,
        "mergeable_state": "clean",
    }
    runner = ScriptedRunner(
        {
            ("git", "status", "--porcelain"): LocalCommandResult(0, ""),
            (
                "gh",
                "api",
                "repos/ktan514/ai-liver-yura/pulls/500",
            ): LocalCommandResult(0, json.dumps(pull)),
            ("git", "fetch", "origin", "feature/work"): LocalCommandResult(0, ""),
            ("git", "switch", "feature/work"): LocalCommandResult(0, ""),
            (
                "git",
                "merge",
                "--ff-only",
                "origin/feature/work",
            ): LocalCommandResult(0, ""),
            ("git", "rev-parse", "HEAD"): LocalCommandResult(0, head + "\n"),
        }
    )
    worktree = TrustedWorktree(runner, Path("/repo"), {"PATH": "/usr/bin"})
    target = HostTarget(340, True, 500, head, True, False, 1, head)

    prepared = worktree.prepare(target)

    assert prepared is not None
    assert prepared.branch == "feature/work"
    assert prepared.start_head == head
    assert not prepared.reconciliation_started
    assert not any(command[:2] == ("git", "commit") for command in runner.commands)


def test_dirty_pr_starts_normal_trunk_merge_on_trusted_host() -> None:
    head = "b" * 40
    pull = {
        "head": {"ref": "feature/work", "sha": head},
        "mergeable": False,
        "mergeable_state": "dirty",
    }
    runner = ScriptedRunner(
        {
            ("git", "status", "--porcelain"): LocalCommandResult(0, ""),
            (
                "gh",
                "api",
                "repos/ktan514/ai-liver-yura/pulls/500",
            ): LocalCommandResult(0, json.dumps(pull)),
            ("git", "fetch", "origin", "feature/work"): LocalCommandResult(0, ""),
            ("git", "switch", "feature/work"): LocalCommandResult(0, ""),
            (
                "git",
                "merge",
                "--ff-only",
                "origin/feature/work",
            ): LocalCommandResult(0, ""),
            ("git", "rev-parse", "HEAD"): LocalCommandResult(0, head + "\n"),
            (
                "git",
                "fetch",
                "origin",
                "rebuild/v2-foundation",
            ): LocalCommandResult(0, ""),
            (
                "git",
                "merge",
                "--no-commit",
                "--no-ff",
                "origin/rebuild/v2-foundation",
            ): LocalCommandResult(1, "競合"),
            (
                "git",
                "diff",
                "--name-only",
                "--diff-filter=U",
            ): LocalCommandResult(0, "docs/a.md\n"),
        }
    )
    worktree = TrustedWorktree(runner, Path("/repo"), {"PATH": "/usr/bin"})
    target = HostTarget(340, True, 500, head, True, False, 1, head)

    prepared = worktree.prepare(target)

    assert prepared is not None
    assert prepared.reconciliation_started
    assert (
        "git",
        "merge",
        "--no-commit",
        "--no-ff",
        "origin/rebuild/v2-foundation",
    ) in runner.commands


def test_finalize_commits_pushes_and_publishes_checkpoint_in_japanese() -> None:
    old_head = "c" * 40
    new_head = "d" * 40
    runner = ScriptedRunner(
        {
            (
                "git",
                "diff",
                "--name-only",
                "--diff-filter=U",
            ): LocalCommandResult(0, ""),
            ("git", "diff", "--check"): LocalCommandResult(0, ""),
            ("git", "add", "-A"): LocalCommandResult(0, ""),
            ("git", "diff", "--cached", "--quiet"): LocalCommandResult(1, ""),
            (
                "git",
                "commit",
                "-m",
                "#340 の実装を進める",
            ): LocalCommandResult(0, ""),
            ("git", "rev-parse", "HEAD"): LocalCommandResult(0, new_head + "\n"),
            (
                "git",
                "push",
                "-u",
                "origin",
                "HEAD:feature/work",
            ): LocalCommandResult(0, ""),
            (
                "gh",
                "api",
                "repos/ktan514/ai-liver-yura/issues/450/comments",
                "-f",
                (
                    "body=## Mission Checkpoint — ACTIVE / 実装更新\n\n"
                    "- Mission state: `ACTIVE`\n"
                    "- current Work: #340\n"
                    "- current PR: #500\n"
                    "- current branch: `feature/work`\n"
                    f"- exact HEAD: `{new_head}`\n"
                    "- 完了済み: Codexによるファイル編集と検証後、"
                    "信頼済みホストがコミット（commit）と送信（push）を実施\n"
                    "- next action: exact HEADのCIを確認し、結果に応じて継続する"
                ),
            ): LocalCommandResult(0, ""),
        }
    )
    worktree = TrustedWorktree(runner, Path("/repo"), {"PATH": "/usr/bin"})
    target = HostTarget(340, True, 500, old_head, True, False, 1, old_head)

    from tools.loop_engine.trusted_worktree import PreparedWorktree

    result = worktree.finalize(
        target,
        PreparedWorktree("feature/work", old_head, 500, False),
        repair=False,
    )

    assert result is not None
    assert result.head_sha == new_head
    assert result.pr_number == 500
    assert ("git", "commit", "-m", "#340 の実装を進める") in runner.commands
