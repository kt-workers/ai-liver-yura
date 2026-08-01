from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_streaming_implementation_is_owned_only_by_subsystem() -> None:
    core_files = sorted((ROOT / "app").rglob("*.py"))
    forbidden = ("subsystems.streaming", "googleapiclient", "obsws", "obswebsocket")
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {name}"
        for path in core_files
        for name in _imports(path)
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    )
    assert violations == []


def test_core_streaming_surface_is_the_integration_package() -> None:
    main_imports = _imports(ROOT / "app" / "__main__.py")
    assert "app.integrations.streaming" in main_imports
