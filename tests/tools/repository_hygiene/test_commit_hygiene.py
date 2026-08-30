from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.repository_hygiene.commit_hygiene import (
    GitInspectionError,
    _decode_nul_fields,
    inspect_commit_range,
    main,
)


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "基底")
    return tmp_path


def _commit(repository: Path, path: str, content: str, message: str) -> str:
    target = repository / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repository, "add", path)
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _range(repository: Path, mutate: Sequence[tuple[str, str, str]]) -> tuple[str, str]:
    base = _git(repository, "rev-parse", "HEAD")
    for path, content, message in mutate:
        _commit(repository, path, content, message)
    return base, _git(repository, "rev-parse", "HEAD")


def _reason_codes(repository: Path, base: str, head: str) -> list[str]:
    return [finding.reason_code for finding in inspect_commit_range(repository, base, head)]


def test_real_and_one_line_commit_pass(repository: Path) -> None:
    base, head = _range(repository, (("README.md", "one-line\n", "一行修正"),))

    assert inspect_commit_range(repository, base, head) == []


def test_single_parent_tree_equal_commit_is_rejected(repository: Path) -> None:
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "commit", "--allow-empty", "-m", "空の履歴操作")
    head = _git(repository, "rev-parse", "HEAD")

    assert _reason_codes(repository, base, head) == ["empty_single_parent_commit"]


@pytest.mark.parametrize("path", ("NOOP", "tmp/example.txt", "tmp/日本語.txt"))
def test_prohibited_placeholder_path_is_rejected(repository: Path, path: str) -> None:
    base, head = _range(repository, ((path, "temporary\n", "仮ファイル"),))

    findings = inspect_commit_range(repository, base, head)

    assert [finding.reason_code for finding in findings] == ["prohibited_placeholder_path"]
    assert findings[0].path == path


def test_placeholder_add_then_delete_has_range_finding(repository: Path) -> None:
    base = _git(repository, "rev-parse", "HEAD")
    _commit(repository, ".trigger", "temporary\n", "仮ファイル追加")
    added = _git(repository, "rev-parse", "HEAD")
    (repository / ".trigger").unlink()
    _git(repository, "add", ".trigger")
    _git(repository, "commit", "-m", "仮ファイル削除")
    head = _git(repository, "rev-parse", "HEAD")

    findings = inspect_commit_range(repository, base, head)

    assert [finding.reason_code for finding in findings] == [
        "prohibited_placeholder_path",
        "prohibited_placeholder_add_delete_pair",
    ]
    assert findings[-1].commit_sha == added
    assert findings[-1].related_commit_sha == head


def test_delete_only_existing_placeholder_is_allowed(repository: Path) -> None:
    _commit(repository, "tmp.txt", "legacy\n", "既存誤作成")
    base = _git(repository, "rev-parse", "HEAD")
    (repository / "tmp.txt").unlink()
    _git(repository, "add", "tmp.txt")
    _git(repository, "commit", "-m", "是正削除")
    head = _git(repository, "rev-parse", "HEAD")

    assert inspect_commit_range(repository, base, head) == []


def test_merge_commit_is_not_empty_only_from_first_parent_tree(repository: Path) -> None:
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "checkout", "-b", "topic")
    _commit(repository, "topic.md", "topic\n", "topic変更")
    _git(repository, "checkout", "main")
    _git(repository, "merge", "--no-ff", "-s", "ours", "topic", "-m", "履歴合流")
    head = _git(repository, "rev-parse", "HEAD")

    assert inspect_commit_range(repository, base, head) == []


def test_merge_commit_specific_placeholder_path_is_rejected(repository: Path) -> None:
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "checkout", "-b", "topic")
    _commit(repository, "topic.md", "topic\n", "topic変更")
    _git(repository, "checkout", "main")
    _commit(repository, "main.md", "main\n", "main変更")
    _git(repository, "merge", "--no-ff", "--no-commit", "topic")
    (repository / "NOOP").write_text("temporary\n", encoding="utf-8")
    _git(repository, "add", "NOOP")
    _git(repository, "commit", "-m", "履歴合流時の誤追加")
    head = _git(repository, "rev-parse", "HEAD")

    findings = inspect_commit_range(repository, base, head)

    assert [finding.reason_code for finding in findings] == [
        "prohibited_placeholder_path",
    ]
    assert findings[0].commit_sha == head
    assert findings[0].path == "NOOP"


def test_nul_path_output_must_be_complete() -> None:
    with pytest.raises(GitInspectionError):
        _decode_nul_fields(b"A\0tmp/example.txt")


def test_nul_path_output_must_be_utf8() -> None:
    with pytest.raises(GitInspectionError):
        _decode_nul_fields(b"A\0tmp/\xff.txt\0")


def test_invalid_revision_has_invocation_exit_two(repository: Path) -> None:
    base = _git(repository, "rev-parse", "HEAD")

    arguments = ("--repository", str(repository), "--base-sha", base, "--head-sha", "not-a-sha")

    assert main(arguments) == 2


def test_findings_are_repeatable_and_commit_message_is_not_interpreted(repository: Path) -> None:
    base = _git(repository, "rev-parse", "HEAD")
    _commit(repository, "code.py", "value = 'noop'\n", "noop という通常語")
    _commit(repository, "NOOP", "temporary\n", "仮ファイル")
    (repository / "NOOP").unlink()
    _git(repository, "add", "NOOP")
    _git(repository, "commit", "-m", "削除")
    head = _git(repository, "rev-parse", "HEAD")

    first = inspect_commit_range(repository, base, head)
    second = inspect_commit_range(repository, base, head)

    assert first == second
    assert [finding.reason_code for finding in first] == [
        "prohibited_placeholder_path",
        "prohibited_placeholder_add_delete_pair",
    ]
