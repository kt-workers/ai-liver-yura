from __future__ import annotations

import tools.commit_hygiene_guard as guard


def _inspect(monkeypatch, message: str) -> list[guard.Finding]:
    monkeypatch.setattr(guard, "_commits", lambda _base, _head: ["deadbeef"])
    monkeypatch.setattr(guard, "_message", lambda _sha: message)
    monkeypatch.setattr(
        guard,
        "_changed_entries",
        lambda _sha: [guard.Change(status="M", path="app/example.py")],
    )
    return guard.inspect_range("base", "head")


def _reasons(findings: list[guard.Finding]) -> list[str]:
    return [finding.reason for finding in findings]


def test_rejects_unscoped_breaking_conventional_prefix(monkeypatch) -> None:
    findings = _inspect(monkeypatch, "fix!: 日本語の不具合を直す")

    assert _reasons(findings) == [
        "許可されていない英語prefixは禁止です: 'fix!:'"
    ]


def test_rejects_scoped_breaking_conventional_prefix(monkeypatch) -> None:
    findings = _inspect(monkeypatch, "fix(v2)!: 日本語の不具合を直す")

    assert _reasons(findings) == [
        "許可されていない英語prefixは禁止です: 'fix(v2)!:'"
    ]


def test_rejects_arbitrary_scoped_conventional_prefix(monkeypatch) -> None:
    findings = _inspect(monkeypatch, "security(v2)!: 日本語の認証処理を直す")

    assert _reasons(findings) == [
        "許可されていない英語prefixは禁止です: 'security(v2)!:'"
    ]


def test_rejects_arbitrary_unscoped_conventional_prefix(monkeypatch) -> None:
    findings = _inspect(monkeypatch, "deps: 日本語で依存関係を更新する")

    assert _reasons(findings) == [
        "許可されていない英語prefixは禁止です: 'deps:'"
    ]


def test_allows_body_technical_prefix(monkeypatch) -> None:
    assert _inspect(monkeypatch, "Body: 姿勢生成契約を更新する (#335)") == []


def test_allows_foundation_technical_prefix(monkeypatch) -> None:
    assert _inspect(monkeypatch, "Foundation: revision検証を追加する (#321)") == []


def test_rejects_scoped_allowed_prefix(monkeypatch) -> None:
    findings = _inspect(monkeypatch, "Body(v2): 姿勢生成契約を更新する (#335)")

    assert _reasons(findings) == [
        "許可されていない英語prefixは禁止です: 'Body(v2):'"
    ]
