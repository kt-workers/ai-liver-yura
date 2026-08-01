from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SUBSYSTEM = ROOT / "subsystems" / "streaming"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_subsystem_only_uses_the_public_app_contract() -> None:
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in SUBSYSTEM.rglob("*.py")
        for import_name in _imports(path)
        if import_name.startswith("app.")
        and not (
            import_name == "app.integrations.streaming"
            or import_name.startswith("app.integrations.streaming.")
        )
    )

    assert violations == []


def test_subsystem_confines_admin_transport_and_has_no_core_sdk_imports() -> None:
    forbidden_prefixes = (
        "app.adapters",
        "app.bootstrap",
        "app.plugins",
        "app.runtime",
        "app.services",
        "fastapi",
        "flask",
        "gui",
        "obswebsocket",
        "starlette",
    )
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in SUBSYSTEM.rglob("*.py")
        for import_name in _imports(path)
        if any(
            import_name == prefix or import_name.startswith(f"{prefix}.")
            for prefix in forbidden_prefixes
        )
        and not (
            import_name.startswith(("fastapi", "starlette"))
            and (
                "admin_api" in path.relative_to(SUBSYSTEM).parts
                or path.relative_to(SUBSYSTEM).as_posix()
                == "api/http_routes.py"
            )
        )
    )

    assert violations == []


def test_external_sdk_imports_are_confined_to_youtube_adapter() -> None:
    sdk_prefixes = (
        "google",
        "google_auth_httplib2",
        "google_auth_oauthlib",
        "googleapiclient",
        "httplib2",
    )
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in SUBSYSTEM.rglob("*.py")
        for import_name in _imports(path)
        if any(
            import_name == prefix or import_name.startswith(f"{prefix}.")
            for prefix in sdk_prefixes
        )
        and "adapters/youtube" not in path.relative_to(ROOT).as_posix()
    )

    assert violations == []


def test_core_bootstrap_and_runtime_do_not_import_subsystem_implementation() -> None:
    core_files = [
        *sorted((ROOT / "app" / "bootstrap").rglob("*.py")),
        *sorted((ROOT / "app" / "runtime").rglob("*.py")),
    ]
    violations = sorted(
        str(path.relative_to(ROOT))
        for path in core_files
        if any(
            import_name == "subsystems.streaming"
            or import_name.startswith("subsystems.streaming.")
            for import_name in _imports(path)
        )
    )

    assert violations == []


def test_core_import_succeeds_when_subsystem_package_is_blocked() -> None:
    script = """
import builtins

original_import = builtins.__import__

def blocked_import(name, *args, **kwargs):
    if name == "subsystems.streaming" or name.startswith("subsystems.streaming."):
        raise ModuleNotFoundError(name)
    return original_import(name, *args, **kwargs)

builtins.__import__ = blocked_import
import app
from app.runtime.runtime_factory import StreamPreparationRuntime
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
