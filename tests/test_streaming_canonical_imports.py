from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def test_legacy_adapter_imports_are_limited_to_compatibility_tests() -> None:
    allowed = {
        "app/bootstrap/streaming_runtime.py",
        "tests/test_streaming_legacy_path_compatibility.py",
        "tests/test_streaming_obs_subsystem_boundaries.py",
        "tests/test_streaming_youtube_subsystem_boundaries.py",
    }
    legacy_prefixes = ("app.adapters.youtube", "app.adapters.obs")
    users = {
        str(path.relative_to(ROOT))
        for root in (ROOT / "app", ROOT / "subsystems", ROOT / "tests")
        for path in root.rglob("*.py")
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for name in _imports(path)
            for prefix in legacy_prefixes
        )
    }
    assert users == allowed


def test_legacy_bootstrap_imports_match_the_migration_baseline() -> None:
    expected = {
        ("app/admin_api/__main__.py", "app.bootstrap.streaming"),
        ("app/admin_api/__main__.py", "app.bootstrap.streaming_runtime"),
        ("app/bootstrap/__init__.py", "app.bootstrap.streaming"),
        ("app/bootstrap/__init__.py", "app.bootstrap.streaming_runtime"),
        ("app/runtime/runtime_factory.py", "app.bootstrap.streaming_runtime"),
    }
    prefixes = (
        "app.bootstrap.streaming",
        "app.bootstrap.streaming_runtime",
    )
    actual = {
        (str(path.relative_to(ROOT)), name)
        for path in (ROOT / "app").rglob("*.py")
        for name in _imports(path)
        if name in prefixes
    }
    assert actual == expected
