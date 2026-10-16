"""移設した境界の依存方向・互換入口・公開Portをまとめて検査する。"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# 同じAST走査を複数ファイルに重複実装せず、境界対象をデータで列挙する。
INWARD_ONLY = (
    "app/usecases/brain_input_meaning.py",
    "app/usecases/task_cleanup.py",
    "app/usecases/ports/cancellation.py",
    "app/usecases/input_reference_context.py",
    "app/usecases/brain_appraisal.py",
    "app/usecases/attention_binding.py",
    "app/usecases/core_lifecycle.py",
    "app/usecases/resource_cleanup.py",
    "app/usecases/ports/core_lifecycle.py",
    "app/usecases/ports/brain_work.py",
    "app/usecases/memory_evidence.py",
    "app/usecases/goal_persistence.py",
    "app/usecases/memory_persistence.py",
    "app/usecases/persistence_tasks.py",
    "app/runtime/kernel/__init__.py",
    "app/runtime/kernel/clock.py",
    "app/runtime/kernel/contracts.py",
    "app/runtime/kernel/cancellation.py",
    "app/runtime/kernel/queue.py",
    "app/runtime/kernel/coordinator.py",
)
MOVED = (
    ("app/composition/input_reference_context.py", "app/usecases/input_reference_context.py"),
    ("app/composition/appraisal.py", "app/usecases/brain_appraisal.py"),
    ("app/composition/attention.py", "app/usecases/attention_binding.py"),
)
FORBIDDEN_OUTER = (
    "app.application",
    "app.bootstrap",
    "app.composition",
    "app.config",
    "app.infrastructure",
    "app.adapters",
    "app.subsystems",
)
KERNEL_FORBIDDEN = (
    "app.infrastructure",
    "app.adapters",
    "app.bootstrap",
    "app.composition",
    "app.application",
    "app.subsystems",
)


def _tree(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)


def _imports(path: str) -> tuple[str, ...]:
    tree = _tree(path)
    package = path.removesuffix(".py").replace("/", ".").rsplit(".", 1)[0]
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                assert node.level <= len(parts), f"{path}:{node.lineno}: relative import"
                prefix = ".".join(parts[: len(parts) - node.level + 1])
                modules.append(".".join(part for part in (prefix, node.module or "") if part))
            else:
                modules.append(node.module or "")
                modules.extend(
                    (node.module or "") + "." + alias.name
                    for alias in node.names
                    if alias.name != "*"
                )
    return tuple(modules)


@pytest.mark.parametrize("path", INWARD_ONLY)
def test_moved_boundary_modules_depend_inward(path: str) -> None:
    forbidden = KERNEL_FORBIDDEN if path.startswith("app/runtime/kernel/") else FORBIDDEN_OUTER
    violations = [
        module for module in _imports(path)
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
    ]
    assert not violations, f"{path}: {violations}"


@pytest.mark.parametrize(("old", "new"), MOVED)
def test_legacy_cognition_paths_only_reexport_the_owner(old: str, new: str) -> None:
    target = new.removesuffix(".py").replace("/", ".")
    definitions = {
        node.name for node in _tree(new).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    exported: set[str] = set()
    for node in _tree(old).body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        assert isinstance(node, ast.ImportFrom), f"{old}: execution logic remains"
        assert node.module == target and node.level == 0
        for alias in node.names:
            assert alias.asname == alias.name and alias.name != "*"
            exported.add(alias.name)
    assert exported == definitions


@pytest.mark.parametrize(
    "path",
    (
        "app/bootstrap/core_components.py",
        "app/composition/cognition_configuration.py",
        "app/composition/cognition.py",
        "app/composition/system_cognition_configuration.py",
    ),
)
def test_consumers_do_not_import_legacy_cognition_owners(path: str) -> None:
    old_modules = {old.removesuffix(".py").replace("/", ".") for old, _ in MOVED}
    assert not (set(_imports(path)) & old_modules)


def test_entrypoint_contains_no_extracted_execution_owners() -> None:
    definitions = {
        node.name for node in _tree("app/application.py").body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert definitions.isdisjoint({
        "InputMeaningBrainWorkPayload",
        "InputMeaningBrainModulePort",
        "UnavailableInputMeaningLiveContextPort",
        "CoreComponents",
        "start_core",
        "stop_core",
        "_close_core_memory",
        "_compose_core",
        "_reap_cleanup",
    })


def test_core_components_are_data_and_composition_facade_only_delegates_lifecycle() -> None:
    components = next(
        node for node in _tree("app/bootstrap/core_components.py").body
        if isinstance(node, ast.ClassDef) and node.name == "CoreComponents"
    )
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in components.body
    )
    facade = next(
        node for node in _tree("app/composition/system_cognition_configuration.py").body
        if isinstance(node, ast.ClassDef) and node.name == "CoreApplication"
    )
    methods = {node.name for node in facade.body if isinstance(node, ast.AsyncFunctionDef)}
    assert methods == {"start", "stop"}
    for node in ast.walk(facade):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {
                "create_task", "shield", "wait_for", "_start_task", "_stop_task"
            }


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        (
            "app/infrastructure/persistence/goal_binding.py",
            {"CoreGoalPersistenceBinding", "GoalPersistenceCommitResult"},
        ),
        (
            "app/infrastructure/persistence/memory_binding.py",
            {"CoreMemoryPersistenceBinding", "CoreMemoryOperation", "_reap"},
        ),
    ),
)
def test_legacy_persistence_paths_only_reexport_application_owners(
    path: str, expected: set[str]
) -> None:
    tree = _tree(path)
    exported = {
        alias.name for node in tree.body
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.usecases.")
        for alias in node.names if alias.asname == alias.name
    }
    assert exported == expected
    assert not any(
        isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        for node in tree.body
    )


def test_neutral_memory_port_imports_without_storage_implementation() -> None:
    program = """
import importlib.abc
import sys
sys.path.insert(0, sys.argv[1])
class RejectOuterImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefixes = ("app.infrastructure", "app.adapters", "app.composition", "psycopg")
        if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in prefixes):
            raise AssertionError("outer import: " + fullname)
        return None
sys.meta_path.insert(0, RejectOuterImports())
from app.domain.contracts.persistence import PersistenceFailureCode, PersistenceOperationResult
from app.usecases.ports.memory_evidence import MemoryEvidencePort
assert PersistenceOperationResult(None, PersistenceFailureCode.CANCELLED).value is None
assert MemoryEvidencePort.__module__ == "app.usecases.ports.memory_evidence"
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(ROOT)],
        cwd=ROOT, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_kernel_clock_contract_and_implementation_have_separate_owners() -> None:
    classes = {
        node.name for node in _tree("app/runtime/kernel/clock.py").body
        if isinstance(node, ast.ClassDef)
    }
    assert classes == {"RuntimeClock"}
    old_classes = {
        node.name for node in _tree("app/infrastructure/scheduling/clock.py").body
        if isinstance(node, ast.ClassDef)
    }
    assert old_classes == {"SystemRuntimeClock", "FakeRuntimeClock"}


def test_moved_execution_files_parse_as_python_310() -> None:
    for path in INWARD_ONLY:
        ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path, feature_version=(3, 10))
