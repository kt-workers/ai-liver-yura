"""実行カーネルを設計された配置へ固定し、外側への依存を再導入しない。"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
KERNEL = ROOT / "app/runtime/kernel"
FORBIDDEN = (
    "app.infrastructure", "app.adapters", "app.bootstrap", "app.composition",
    "app.application", "app.subsystems",
)


@pytest.mark.parametrize(
    "name", ["__init__", "clock", "contracts", "cancellation", "queue", "coordinator"]
)
def test_kernel_never_imports_external_implementations(name: str) -> None:
    source = (KERNEL / (name + ".py")).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        for module in modules:
            assert not any(
                module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN
            )


@pytest.mark.parametrize("name", ["contracts", "cancellation", "queue", "coordinator"])
def test_old_paths_only_reexport_the_canonical_implementation(name: str) -> None:
    source = (ROOT / "app/infrastructure/scheduling" / (name + ".py")).read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            assert isinstance(node.value.value, str)
        else:
            assert isinstance(node, ast.ImportFrom)
            assert node.module == "app.runtime.kernel." + name
            assert all(alias.name == alias.asname for alias in node.names)


def test_brain_runtime_uses_core_kernel_not_infrastructure() -> None:
    source = (ROOT / "app/usecases/brain_integration_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "app.runtime.kernel" in modules
    assert not any(module and module.startswith("app.infrastructure") for module in modules)


def test_clock_implementation_is_not_owned_by_the_kernel() -> None:
    tree = ast.parse((KERNEL / "clock.py").read_text(encoding="utf-8"))
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert classes == {"RuntimeClock"}
    source = (ROOT / "app/infrastructure/scheduling/clock.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert classes == {"SystemRuntimeClock", "FakeRuntimeClock"}


def test_canonical_import_does_not_load_external_packages_in_a_fresh_process() -> None:
    program = (
        "import sys\n"
        "import app.runtime.kernel\n"
        f"prefixes = {FORBIDDEN!r}\n"
        "loaded = [name for name in sys.modules "
        "if any(name == p or name.startswith(p + '.') for p in prefixes)]\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True,
        timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
