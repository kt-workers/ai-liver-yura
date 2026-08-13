from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass


FORBIDDEN_PLACEHOLDER_PATHS = frozenset(
    {
        "NOOP",
        "nonexistent",
        ".trigger",
        "TRIGGER",
        "DUMMY",
        "dummy",
    }
)

FORBIDDEN_TRIGGER_MESSAGES = frozenset(
    {
        "x",
        "noop",
        "no-op",
        "trigger",
        "ci trigger",
        "test trigger",
        "tmp",
        "temporary",
    }
)

ALLOWED_ASCII_TECHNICAL_PREFIXES = frozenset({"Body", "Foundation"})

JAPANESE_CHARACTER_PATTERN = re.compile(
    r"[\u3041-\u3096\u30a1-\u30fa\u3400-\u4dbf\u4e00-\u9fff"
    r"\uff66-\uff6f\uff71-\uff9d]"
)
ASCII_COLON_PREFIX_PATTERN = re.compile(
    r"^(?P<prefix>[A-Za-z][A-Za-z0-9._-]*)"
    r"(?P<scope>\([^)]*\))?"
    r"(?P<breaking>!)?:"
)


@dataclass(frozen=True)
class Finding:
    commit_sha: str
    reason: str


@dataclass(frozen=True)
class Change:
    status: str
    path: str


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _commits(base_sha: str, head_sha: str) -> list[str]:
    output = _git("rev-list", "--reverse", f"{base_sha}..{head_sha}")
    return [line.strip() for line in output.splitlines() if line.strip()]


def _message(commit_sha: str) -> str:
    return _git("show", "-s", "--format=%B", commit_sha).strip()


def _parents(commit_sha: str) -> list[str]:
    parts = _git("rev-list", "--parents", "-n", "1", commit_sha).strip().split()
    if not parts:
        return []
    return parts[1:]


def _parse_name_status(output: str) -> list[Change]:
    changes: list[Change] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        status, separator, path = line.partition("\t")
        if not separator or not status or not path:
            raise ValueError(f"unexpected git --name-status output: {line!r}")
        changes.append(Change(status=status, path=path))
    return changes


def _changed_entries(commit_sha: str) -> list[Change]:
    parents = _parents(commit_sha)
    if parents:
        output = _git(
            "diff",
            "--name-status",
            "--no-renames",
            parents[0],
            commit_sha,
            "--",
        )
    else:
        output = _git(
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "--no-renames",
            "-r",
            commit_sha,
        )
    return _parse_name_status(output)


def _subject(message: str) -> str:
    if not message:
        return ""
    return message.splitlines()[0].strip()


def _forbidden_ascii_prefix(subject: str) -> str | None:
    match = ASCII_COLON_PREFIX_PATTERN.search(subject)
    if match is None:
        return None

    prefix = match.group("prefix")
    scope = match.group("scope")
    breaking = match.group("breaking")
    if prefix in ALLOWED_ASCII_TECHNICAL_PREFIXES and scope is None and breaking is None:
        return None
    return match.group(0)


def inspect_range(base_sha: str, head_sha: str) -> list[Finding]:
    findings: list[Finding] = []

    for commit_sha in _commits(base_sha, head_sha):
        message = _message(commit_sha)
        subject = _subject(message)
        changes = _changed_entries(commit_sha)

        if not changes:
            findings.append(
                Finding(
                    commit_sha=commit_sha,
                    reason="空コミットまたは履歴生成だけのコミットは禁止です",
                )
            )
            continue

        if not JAPANESE_CHARACTER_PATTERN.search(subject):
            findings.append(
                Finding(
                    commit_sha=commit_sha,
                    reason="コミット件名は日本語を主要言語として記述してください",
                )
            )

        forbidden_prefix = _forbidden_ascii_prefix(subject)
        if forbidden_prefix is not None:
            findings.append(
                Finding(
                    commit_sha=commit_sha,
                    reason=(
                        "許可されていない英語prefixは禁止です: "
                        f"{forbidden_prefix!r}"
                    ),
                )
            )

        forbidden_changes = sorted(
            change.path
            for change in changes
            if change.path in FORBIDDEN_PLACEHOLDER_PATHS
            and change.status != "D"
        )
        if forbidden_changes:
            findings.append(
                Finding(
                    commit_sha=commit_sha,
                    reason=(
                        "placeholder用パスの追加・変更は禁止です: "
                        + ", ".join(forbidden_changes)
                    ),
                )
            )

        normalized_subject = " ".join(subject.lower().split())
        if normalized_subject in FORBIDDEN_TRIGGER_MESSAGES:
            findings.append(
                Finding(
                    commit_sha=commit_sha,
                    reason=f"履歴生成だけの件名は禁止です: {subject!r}",
                )
            )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="V2 PRのコミット履歴にplaceholder/no-op/英語件名がないか検査します。"
    )
    parser.add_argument("--base", required=True, help="信頼済みPR base SHA")
    parser.add_argument("--head", required=True, help="PR head SHA")
    args = parser.parse_args()

    findings = inspect_range(args.base, args.head)
    if not findings:
        print(f"コミット衛生検査 PASS: {args.base}..{args.head}")
        return 0

    print("コミット衛生検査 FAIL", file=sys.stderr)
    for finding in findings:
        print(
            f"- {finding.commit_sha}: {finding.reason}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
