from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
GAME_INTEGRATION = ROOT / "app" / "integrations" / "games"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_game_integration_does_not_depend_on_core_or_plugins() -> None:
    forbidden_prefixes = (
        "app.bootstrap",
        "app.core",
        "app.domain",
        "app.plugins",
        "app.runtime",
        "app.usecases",
        "subsystems.games",
    )
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in GAME_INTEGRATION.rglob("*.py")
        for import_name in _imports(path)
        if any(
            import_name == prefix or import_name.startswith(f"{prefix}.")
            for prefix in forbidden_prefixes
        )
    )

    assert violations == []


def test_runtime_is_not_coupled_to_unused_game_gateway() -> None:
    runtime_files = [
        *sorted((ROOT / "app" / "bootstrap").rglob("*.py")),
        *sorted((ROOT / "app" / "runtime").rglob("*.py")),
    ]
    violations = sorted(
        str(path.relative_to(ROOT))
        for path in runtime_files
        if any(
            import_name == "app.integrations.games"
            or import_name.startswith("app.integrations.games.")
            for import_name in _imports(path)
        )
    )

    assert violations == []


def test_contract_shell_does_not_restore_legacy_games() -> None:
    assert not (ROOT / "app" / "plugins" / "games").exists()

    integration_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(GAME_INTEGRATION.rglob("*.py"))
    ).lower()

    assert "shiritori" not in integration_source
    assert "games.shiritori" not in integration_source


def test_subsystem_shell_contains_documentation_only() -> None:
    subsystem_root = ROOT / "subsystems" / "games"

    assert (subsystem_root / "README.md").is_file()
    assert (subsystem_root / "contracts" / "README.md").is_file()
    assert list(subsystem_root.rglob("*.py")) == []
