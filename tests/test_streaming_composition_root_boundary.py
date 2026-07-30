from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNTIME_PATH = ROOT / "app/bootstrap/runtime.py"
FORBIDDEN_IMPORTS = (
    "app.plugins.youtube_streaming",
    "app.adapters.youtube",
    "app.adapters.obs",
    "app.adapters.streaming",
    "app.ports.streaming_control",
    "app.ports.streaming_preparation",
    "app.ports.youtube_live_chat",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module)
    return values


def test_core_runtime_does_not_import_streaming_youtube_or_obs_modules() -> None:
    violations = sorted(
        name
        for name in _imports(RUNTIME_PATH)
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in FORBIDDEN_IMPORTS
        )
    )

    assert violations == []


def test_core_runtime_import_succeeds_when_streaming_modules_are_blocked() -> None:
    script = """
import builtins
import importlib
import sys

# app.bootstrap keeps its public Streaming exports eager until a later migration.
import app.bootstrap

sys.modules.pop("app.bootstrap.runtime", None)
forbidden = (
    "app.plugins.youtube_streaming",
    "app.adapters.youtube",
    "app.adapters.obs",
    "app.adapters.streaming",
    "app.ports.streaming_control",
    "app.ports.streaming_preparation",
    "app.ports.youtube_live_chat",
)
original_import = builtins.__import__

def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden):
        raise ModuleNotFoundError(f"blocked Streaming import: {name}")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = blocked_import
importlib.import_module("app.bootstrap.runtime")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
