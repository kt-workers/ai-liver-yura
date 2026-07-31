from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
WRAPPERS = (
    ROOT / "app" / "adapters" / "youtube" / "__init__.py",
    ROOT / "app" / "adapters" / "obs" / "__init__.py",
)


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


def test_remaining_wrappers_are_one_step_declarative_reexports() -> None:
    allowed_nodes = (ast.Expr, ast.Import, ast.ImportFrom, ast.Assign)
    for path in WRAPPERS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert all(isinstance(node, allowed_nodes) for node in tree.body)
        assert not any(
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(tree)
        )
        assert all(
            name.startswith("subsystems.streaming.adapters")
            for name in _imports(path)
        )


def test_subsystem_never_imports_legacy_streaming_paths() -> None:
    forbidden = (
        "app.adapters.youtube",
        "app.adapters.obs",
        "app.adapters.streaming",
        "app.bootstrap.streaming",
        "app.plugins.youtube_streaming",
        "app.ports.streaming",
        "app.ports.youtube",
    )
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {name}"
        for path in (ROOT / "subsystems" / "streaming").rglob("*.py")
        for name in _imports(path)
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    )
    assert violations == []


def test_wrapper_import_has_no_sdk_secret_network_or_runtime_side_effect() -> None:
    script = """
import socket
import sys
from subsystems.streaming.config.secrets import EnvironmentSecretProvider

def forbidden(*args, **kwargs):
    raise AssertionError((args, kwargs))

EnvironmentSecretProvider.get_secret = forbidden
socket.create_connection = forbidden
before = set(sys.modules)
import app.adapters.youtube
import app.adapters.obs
after = set(sys.modules) - before
sdk_prefixes = ('google.oauth2', 'googleapiclient', 'obsws_python')
assert not any(name.startswith(sdk_prefixes) for name in after)
assert 'app.bootstrap.streaming_runtime' not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
