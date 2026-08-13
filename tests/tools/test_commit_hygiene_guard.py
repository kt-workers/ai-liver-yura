from __future__ import annotations

import tools.commit_hygiene_guard as guard


def _stub_range(
    monkeypatch,
    *,
    message: str,
    changes: list[guard.Change],
) -> None:
    monkeypatch.setattr(guard, "_commits", lambda _base, _head: ["deadbeef"])
    monkeypatch.setattr(guard, "_message", lambda _sha: message)
    monkeypatch.setattr(guard, "_changed_entries", lambda _sha: changes)


def test_rejects_nonexistent_placeholder_addition(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="x",
        changes=[guard.Change(status="A", path="nonexistent")],
    )

    findings = guard.inspect_range("base", "head")

    reasons = {finding.reason for finding in findings}
    assert "placeholder用パスの追加・変更は禁止です: nonexistent" in reasons
    assert "履歴生成だけの件名は禁止です: 'x'" in reasons


def test_rejects_noop_placeholder_addition(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="noop",
        changes=[guard.Change(status="A", path="NOOP")],
    )

    findings = guard.inspect_range("base", "head")

    reasons = {finding.reason for finding in findings}
    assert "placeholder用パスの追加・変更は禁止です: NOOP" in reasons
    assert "履歴生成だけの件名は禁止です: 'noop'" in reasons


def test_allows_corrective_placeholder_deletion(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="V2管理: 誤って追加されたplaceholderを削除する (#384)",
        changes=[guard.Change(status="D", path="NOOP")],
    )

    assert guard.inspect_range("base", "head") == []


def test_rejects_placeholder_modification(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="V2管理: placeholderを変更する (#384)",
        changes=[guard.Change(status="M", path="NOOP")],
    )

    assert [finding.reason for finding in guard.inspect_range("base", "head")] == [
        "placeholder用パスの追加・変更は禁止です: NOOP"
    ]


def test_rejects_empty_commit(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="レビューを再実行する",
        changes=[],
    )

    findings = guard.inspect_range("base", "head")

    assert [finding.reason for finding in findings] == [
        "空コミットまたは履歴生成だけのコミットは禁止です"
    ]


def test_rejects_ascii_only_subject(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="Implement repair guard",
        changes=[guard.Change(status="M", path="tools/commit_hygiene_guard.py")],
    )

    findings = guard.inspect_range("base", "head")

    assert [finding.reason for finding in findings] == [
        "コミット件名は日本語を主要言語として記述してください"
    ]


def test_rejects_japanese_punctuation_without_japanese_letters(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="API・schema update",
        changes=[guard.Change(status="M", path="tools/commit_hygiene_guard.py")],
    )

    findings = guard.inspect_range("base", "head")

    assert [finding.reason for finding in findings] == [
        "コミット件名は日本語を主要言語として記述してください"
    ]


def test_rejects_halfwidth_prolonged_mark_without_japanese_letters(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="APIｰschema update",
        changes=[guard.Change(status="M", path="tools/commit_hygiene_guard.py")],
    )

    findings = guard.inspect_range("base", "head")

    assert [finding.reason for finding in findings] == [
        "コミット件名は日本語を主要言語として記述してください"
    ]


def test_rejects_english_conventional_commit_prefix(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="fix(v2): 不正なrevisionを拒否する",
        changes=[guard.Change(status="M", path="app/domain/contracts/common.py")],
    )

    findings = guard.inspect_range("base", "head")

    assert [finding.reason for finding in findings] == [
        "許可されていない英語prefixは禁止です: 'fix(v2):'"
    ]


def test_allows_small_legitimate_commit(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="Foundation: 不正なrevisionを拒否する (#321)",
        changes=[guard.Change(status="M", path="app/domain/contracts/common.py")],
    )

    assert guard.inspect_range("base", "head") == []


def test_allows_legitimate_test_file(monkeypatch) -> None:
    _stub_range(
        monkeypatch,
        message="Foundation: revision検証の回帰テストを追加する (#321)",
        changes=[guard.Change(status="A", path="tests/domain/contracts/test_common.py")],
    )

    assert guard.inspect_range("base", "head") == []


def test_changed_entries_use_first_parent_for_merge(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        if args == ("rev-list", "--parents", "-n", "1", "merge-sha"):
            return "merge-sha first-parent second-parent\n"
        if args == (
            "diff",
            "--name-status",
            "--no-renames",
            "first-parent",
            "merge-sha",
            "--",
        ):
            return "M\tapp/domain/contracts/common.py\n"
        raise AssertionError(f"unexpected git call: {args!r}")

    monkeypatch.setattr(guard, "_git", fake_git)

    assert guard._changed_entries("merge-sha") == [
        guard.Change(status="M", path="app/domain/contracts/common.py")
    ]
    assert calls == [
        ("rev-list", "--parents", "-n", "1", "merge-sha"),
        (
            "diff",
            "--name-status",
            "--no-renames",
            "first-parent",
            "merge-sha",
            "--",
        ),
    ]


def test_changed_entries_use_root_diff_for_root_commit(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        if args == ("rev-list", "--parents", "-n", "1", "root-sha"):
            return "root-sha\n"
        if args == (
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "--no-renames",
            "-r",
            "root-sha",
        ):
            return "A\tREADME.md\n"
        raise AssertionError(f"unexpected git call: {args!r}")

    monkeypatch.setattr(guard, "_git", fake_git)

    assert guard._changed_entries("root-sha") == [
        guard.Change(status="A", path="README.md")
    ]
    assert calls == [
        ("rev-list", "--parents", "-n", "1", "root-sha"),
        (
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "--no-renames",
            "-r",
            "root-sha",
        ),
    ]
