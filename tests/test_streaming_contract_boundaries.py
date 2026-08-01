from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
STREAMING_INTEGRATION = ROOT / "app" / "integrations" / "streaming"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_public_contract_has_no_concrete_or_transport_imports() -> None:
    forbidden_prefixes = (
        "app.adapters",
        "app.admin_api",
        "app.bootstrap",
        "app.core",
        "app.plugins",
        "app.runtime",
        "app.usecases",
        "fastapi",
        "flask",
        "googleapiclient",
        "gui",
        "obswebsocket",
        "starlette",
        "subsystems.streaming",
    )
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in STREAMING_INTEGRATION.rglob("*.py")
        for import_name in _imports(path)
        if any(
            import_name == prefix or import_name.startswith(f"{prefix}.")
            for prefix in forbidden_prefixes
        )
    )

    assert violations == []


def test_public_contract_does_not_expose_adapter_specific_names() -> None:
    forbidden_names = ("youtube", "obs_websocket", "googleapiclient")
    violations = sorted(
        str(path.relative_to(ROOT))
        for path in STREAMING_INTEGRATION.rglob("*.py")
        if any(
            name in path.read_text(encoding="utf-8").lower()
            for name in forbidden_names
        )
    )

    assert violations == []


def test_runtime_is_not_wired_to_the_new_public_contract() -> None:
    runtime_files = [
        *sorted((ROOT / "app" / "bootstrap").rglob("*.py")),
        *sorted((ROOT / "app" / "runtime").rglob("*.py")),
    ]
    violations = sorted(
        str(path.relative_to(ROOT))
        for path in runtime_files
        if any(
            import_name == "app.integrations.streaming"
            or import_name.startswith("app.integrations.streaming.")
            for import_name in _imports(path)
        )
    )

    assert violations == []


def test_subsystem_contract_directory_contains_documentation_only() -> None:
    contracts_root = ROOT / "subsystems" / "streaming" / "contracts"

    assert (contracts_root / "README.md").is_file()
    assert list(contracts_root.rglob("*.py")) == []
