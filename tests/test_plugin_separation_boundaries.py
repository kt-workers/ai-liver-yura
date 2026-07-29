from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

from app.core.plugins import PluginContext, PluginManager
from app.domain.activities import Activity

ROOT = Path(__file__).parents[1]


def _python_files(relative: str) -> list[Path]:
    return sorted((ROOT / relative).rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module)
    return values


def _imports_with_prefix(paths: list[Path], prefix: str) -> set[str]:
    return {
        name
        for path in paths
        for name in _imports(path)
        if name == prefix or name.startswith(f"{prefix}.")
    }


def _assert_no_import_prefix(paths: list[Path], prefixes: tuple[str, ...]) -> None:
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {name}"
        for path in paths
        for name in _imports(path)
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)
    )
    assert violations == []


def test_core_runtime_and_usecases_do_not_import_concrete_plugins() -> None:
    """Coreの実行・業務ロジックからPlugin具象への新規依存を禁止する。"""

    _assert_no_import_prefix(
        _python_files("app/runtime") + _python_files("app/usecases"),
        ("app.plugins",),
    )


def test_plugins_do_not_import_core_runtime_or_usecase_implementations() -> None:
    """Pluginは共有契約を使い、Coreの実装詳細へ逆依存しない。"""

    _assert_no_import_prefix(
        _python_files("app/plugins"),
        ("app.runtime", "app.usecases", "app.core"),
    )


def test_bootstrap_concrete_plugin_imports_match_migration_baseline() -> None:
    """Phase 2で除去する静的importを固定し、これ以上の増加を防止する。

    baselineは許容設計ではなく移行負債の一覧である。Phase 2以降は削除に合わせて
    この集合を縮小し、最終的に空集合にする。
    """

    actual = _imports_with_prefix(_python_files("app/bootstrap"), "app.plugins")
    expected_migration_debt = {
        "app.plugins.llm_provider",
        "app.plugins.youtube_streaming.application",
        "app.plugins.youtube_streaming.application.service",
        "app.plugins.youtube_streaming.domain",
        "app.plugins.youtube_streaming.public.activity_provider",
        "app.plugins.youtube_streaming.public.evidence",
        "app.plugins.youtube_streaming.public.registration",
    }

    assert actual == expected_migration_debt


class _Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _ActivityGateway:
    def register(self, activity: Activity) -> Activity:
        return activity


class _LlmGateway:
    async def generate_response(self, request: object) -> str:
        return "{}"


def test_plugin_manager_operates_with_zero_registered_plugins() -> None:
    """Pluginが一つもなくてもPlugin基盤そのものは正常に成立する。"""

    manager = PluginManager()
    context = PluginContext(
        llm_gateway=_LlmGateway(),
        activity_gateway=_ActivityGateway(),
        clock=_Clock(),
        configuration={},
    )

    manager.initialize_enabled_plugins(context, {})

    assert manager.list_capabilities() == frozenset()
    assert manager.list_activity_definitions() == ()
    assert manager.get_plugins_by_capability("missing") == []


def test_core_entrypoint_does_not_import_streaming_or_game_plugins() -> None:
    """通常Coreの入口は配信・ゲームPluginの存在を前提にしない。"""

    _assert_no_import_prefix(
        [ROOT / "app/__main__.py"],
        (
            "app.plugins.games",
            "app.plugins.youtube_streaming",
            "app.admin_api",
            "app.adapters.obs",
            "app.adapters.youtube",
        ),
    )
