from __future__ import annotations

import ast
from pathlib import Path

from subsystems.streaming.adapters.obs import (
    FakeObsPreparationAdapter,
    ObsWebSocketPreparationAdapter,
    ObsWebSocketStreamingControlAdapter,
)

ROOT = Path(__file__).parents[1]
OBS_ADAPTER = ROOT / "subsystems" / "streaming" / "adapters" / "obs"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_obs_adapter_has_no_core_or_youtube_dependency() -> None:
    forbidden_prefixes = (
        "app.adapters",
        "app.bootstrap",
        "app.plugins",
        "app.runtime",
        "app.services",
        "gui",
        "subsystems.streaming.adapters.youtube",
    )
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in OBS_ADAPTER.rglob("*.py")
        for import_name in _imports(path)
        if any(
            import_name == prefix or import_name.startswith(f"{prefix}.")
            for prefix in forbidden_prefixes
        )
    )

    assert violations == []


def test_core_python_files_do_not_import_obs_sdk() -> None:
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in (ROOT / "app").rglob("*.py")
        for import_name in _imports(path)
        if import_name == "obsws_python"
        or import_name.startswith(("obsws_python.", "websocket.obs"))
    )

    assert violations == []


def test_legacy_obs_paths_are_one_way_compatibility_imports() -> None:
    legacy_root = ROOT / "app" / "adapters" / "obs"
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in legacy_root.rglob("*.py")
        for import_name in _imports(path)
        if not import_name.startswith("subsystems.streaming.adapters.obs")
    )
    implementations = sorted(
        f"{path.relative_to(ROOT)}:{node.name}"
        for path in legacy_root.rglob("*.py")
        for node in ast.walk(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )

    assert violations == []
    assert implementations == []


def test_legacy_class_names_resolve_to_subsystem_implementations() -> None:
    from app.adapters.obs import (
        ObsWebSocketPreparationAdapter as LegacyPreparation,
    )
    from app.adapters.obs import (
        ObsWebSocketStreamingControlAdapter as LegacyControl,
    )
    from app.adapters.streaming.fake_obs_preparation_adapter import (
        FakeObsPreparationAdapter as LegacyFakePreparation,
    )

    assert LegacyPreparation is ObsWebSocketPreparationAdapter
    assert LegacyControl is ObsWebSocketStreamingControlAdapter
    assert LegacyFakePreparation is FakeObsPreparationAdapter
