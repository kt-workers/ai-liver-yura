"""Pull Request の commit range を読み取り専用で検査する。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PROHIBITED_EXACT_PATHS = frozenset(
    {
        "NOOP",
        "nonexistent",
        ".trigger",
        ".issue_sync_marker",
        "tmp-never-used",
        "tmp.txt",
        "ISSUE_PLAN.md",
        "DO_NOT_USE",
    }
)
PROHIBITED_PREFIXES = ("tmp/",)


@dataclass(frozen=True)
class HygieneFinding:
    """安定した機械可読 reason code と日本語説明を持つ検出結果。"""

    reason_code: str
    commit_sha: str | None
    path: str | None
    related_commit_sha: str | None
    message_ja: str


class GitInspectionError(RuntimeError):
    """読み取り専用 Git 検査が成立しなかったことを表す。"""


def _git(repository: Path, arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "Git コマンドが失敗しました。"
        )
        raise GitInspectionError(detail)
    return completed.stdout


def _git_bytes(repository: Path, arguments: Sequence[str]) -> bytes:
    """pathをGitの表示用quoteへ変換させずbyte列として取得する。"""

    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
        text=False,
    )
    if completed.returncode != 0:
        raw_detail = completed.stderr or completed.stdout
        detail = raw_detail.decode("utf-8", errors="replace").strip()
        raise GitInspectionError(detail or "Git コマンドが失敗しました。")
    return completed.stdout


def _resolve_commit(repository: Path, revision: str) -> str:
    return _git(repository, ("rev-parse", "--verify", f"{revision}^{{commit}}")).strip()


def _is_prohibited_path(path: str) -> bool:
    return path in PROHIBITED_EXACT_PATHS or path.startswith(PROHIBITED_PREFIXES)


def _decode_nul_fields(output: bytes) -> list[str]:
    """NUL区切りのGit出力を実path文字列へ復号する。"""

    if output and not output.endswith(b"\0"):
        raise GitInspectionError("Git のNUL区切りpath出力が途中で終了しています。")
    raw_fields = output.split(b"\0")
    if raw_fields and raw_fields[-1] == b"":
        raw_fields.pop()
    try:
        return [field.decode("utf-8") for field in raw_fields]
    except UnicodeDecodeError as error:
        raise GitInspectionError("Git のpathをUTF-8として復号できません。") from error


def _commit_paths(repository: Path, commit_sha: str) -> list[tuple[str, str]]:
    parents = _git(repository, ("show", "-s", "--format=%P", commit_sha)).split()
    arguments: tuple[str, ...]
    if parents:
        arguments = (
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "-z",
            parents[0],
            commit_sha,
        )
    else:
        arguments = (
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "-r",
            "-z",
            commit_sha,
        )
    fields = _decode_nul_fields(_git_bytes(repository, arguments))
    paths: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if not status:
            raise GitInspectionError("Git の path status 出力を解釈できません。")
        if status.startswith(("R", "C")):
            if index + 1 >= len(fields):
                raise GitInspectionError("Git の rename/copy status 出力を解釈できません。")
            index += 1
            path = fields[index]
            index += 1
        else:
            if index >= len(fields):
                raise GitInspectionError("Git の path status 出力を解釈できません。")
            path = fields[index]
            index += 1
        paths.append((status, path))
    return paths


def inspect_commit_range(repository: Path, base_sha: str, head_sha: str) -> list[HygieneFinding]:
    """`base_sha..head_sha` を決定論的に検査し、finding を順序どおり返す。"""

    try:
        base_commit = _resolve_commit(repository, base_sha)
        head_commit = _resolve_commit(repository, head_sha)
    except GitInspectionError:
        return [
            HygieneFinding(
                reason_code="invalid_revision_range",
                commit_sha=None,
                path=None,
                related_commit_sha=None,
                message_ja="base SHA または head SHA を commit として解決できません。",
            )
        ]

    try:
        commits = [
            commit
            for commit in _git(
                repository,
                ("rev-list", "--reverse", "--topo-order", f"{base_commit}..{head_commit}"),
            ).splitlines()
            if commit
        ]
        findings: list[HygieneFinding] = []
        placeholder_additions: dict[str, str] = {}
        placeholder_deletions: dict[str, str] = {}
        for commit_sha in commits:
            parents = _git(repository, ("show", "-s", "--format=%P", commit_sha)).split()
            if len(parents) == 1:
                commit_tree = _git(repository, ("show", "-s", "--format=%T", commit_sha)).strip()
                parent_tree = _git(repository, ("show", "-s", "--format=%T", parents[0])).strip()
                if commit_tree == parent_tree:
                    findings.append(
                        HygieneFinding(
                            reason_code="empty_single_parent_commit",
                            commit_sha=commit_sha,
                            path=None,
                            related_commit_sha=None,
                            message_ja="single-parent commit の tree が親 commit と同一です。",
                        )
                    )
            for status, path in _commit_paths(repository, commit_sha):
                status_kind = status[0]
                if not _is_prohibited_path(path):
                    continue
                if status_kind in {"A", "M", "R", "C"}:
                    findings.append(
                        HygieneFinding(
                            reason_code="prohibited_placeholder_path",
                            commit_sha=commit_sha,
                            path=path,
                            related_commit_sha=None,
                            message_ja=(
                                "共有履歴へ禁止 placeholder path を追加または変更しています。"
                            ),
                        )
                    )
                if status_kind == "A":
                    placeholder_additions.setdefault(path, commit_sha)
                elif status_kind == "D" and path in placeholder_additions:
                    placeholder_deletions.setdefault(path, commit_sha)
        for path in sorted(placeholder_deletions):
            findings.append(
                HygieneFinding(
                    reason_code="prohibited_placeholder_add_delete_pair",
                    commit_sha=placeholder_additions[path],
                    path=path,
                    related_commit_sha=placeholder_deletions[path],
                    message_ja="同一検査範囲内で禁止 placeholder path を追加後に削除しています。",
                )
            )
        return findings
    except GitInspectionError:
        return [
            HygieneFinding(
                reason_code="git_inspection_failed",
                commit_sha=None,
                path=None,
                related_commit_sha=None,
                message_ja="読み取り専用 Git 検査に失敗しました。",
            )
        ]


def _format_finding(finding: HygieneFinding) -> str:
    fields = [f"reason_code={finding.reason_code}"]
    for name, value in (
        ("commit_sha", finding.commit_sha),
        ("path", finding.path),
        ("related_commit_sha", finding.related_commit_sha),
    ):
        if value is not None:
            fields.append(f"{name}={value}")
    fields.append(f"message_ja={finding.message_ja}")
    return " ".join(fields)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint。検査以外の Git mutation は実行しない。"""

    parser = argparse.ArgumentParser(description="Pull Request の commit hygiene を検査します。")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    findings = inspect_commit_range(arguments.repository, arguments.base_sha, arguments.head_sha)
    for finding in findings:
        print(_format_finding(finding))
    if not findings:
        return 0
    if findings[0].reason_code in {"invalid_revision_range", "git_inspection_failed"}:
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
