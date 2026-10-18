"""移設した境界の依存方向・互換入口・公開Portをまとめて検査する。"""

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import is_dataclass
from pathlib import Path

import pytest

from app.bootstrap.speech_configuration import CoreSpeechDelivery as PublicSpeechDelivery
from app.bootstrap.system_cognition_configuration import CoreApplication
from app.domain.llm.ports import LLMRolePort as DomainLLMRolePort
from app.infrastructure import scheduling as legacy_scheduling
from app.runtime import kernel
from app.usecases.appraisal import DeepAppraisalInterpreter
from app.usecases.body_motion_planning import BodyMotionPlanner
from app.usecases.goal_planning import GoalPlanner
from app.usecases.input_meaning import InputMeaningInterpreter
from app.usecases.ports.llm import LLMRolePort
from app.usecases.speech_delivery import CoreSpeechDelivery as CanonicalSpeechDelivery

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


def test_moved_boundary_modules_depend_inward() -> None:
    """同じ層間依存規約を、全移設モジュールの単一監査として実施する。"""
    violations: list[str] = []
    for path in INWARD_ONLY:
        forbidden = KERNEL_FORBIDDEN if path.startswith("app/runtime/kernel/") else FORBIDDEN_OUTER
        violations.extend(
            f"{path}: {module}"
            for module in _imports(path)
            if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
        )
    assert not violations, "依存方向違反:\n" + "\n".join(violations)


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


def test_core_components_are_data_and_bootstrap_delegates_lifecycle() -> None:
    components = next(
        node for node in _tree("app/bootstrap/core_components.py").body
        if isinstance(node, ast.ClassDef) and node.name == "CoreComponents"
    )
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in components.body
    )
    facade = next(
        node for node in _tree("app/bootstrap/core_application.py").body
        if isinstance(node, ast.ClassDef) and node.name == "CoreApplication"
    )
    assembly_classes = {
        node.name for node in _tree("app/bootstrap/system_cognition_configuration.py").body
        if isinstance(node, ast.ClassDef)
    }
    assert "CoreApplication" not in assembly_classes
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



@pytest.mark.parametrize("name", ("contracts", "cancellation", "queue", "coordinator"))
def test_legacy_kernel_paths_only_reexport_canonical_implementation(name: str) -> None:
    path = "app/infrastructure/scheduling/" + name + ".py"
    target = "app.runtime.kernel." + name
    for node in _tree(path).body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        assert isinstance(node, ast.ImportFrom)
        assert node.level == 0 and node.module == target
        assert all(alias.name == alias.asname for alias in node.names)


@pytest.mark.parametrize(
    ("path", "names"),
    (
        (
            "app/infrastructure/persistence/contracts.py",
            ("PersistenceError", "PersistenceFailureCode"),
        ),
        ("app/infrastructure/persistence/runtime.py", ("PersistenceOperationResult",)),
    ),
)
def test_persistence_compatibility_paths_reexport_domain_contracts(
    path: str, names: tuple[str, ...]
) -> None:
    tree = _tree(path)
    definitions = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert definitions.isdisjoint(names)
    exported = {
        (alias.name, alias.asname)
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.domain.contracts.persistence"
        for alias in node.names
    }
    assert all((name, name) in exported for name in names)


def test_goal_persistence_owner_identity_has_one_domain_definition() -> None:
    for path in (
        "app/infrastructure/persistence/goal_snapshot_codec.py",
        "app/usecases/goal_persistence.py",
    ):
        tree = _tree(path)
        aliases = {
            (alias.name, alias.asname)
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "app.domain.contracts.persistence"
            for alias in node.names
        }
        assert ("GOAL_PERSISTENCE_OWNER_ID", "OWNER_ID") in aliases
        assert not any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "OWNER_ID"
                for target in node.targets
            )
            for node in tree.body
        )


def test_appraisal_uses_read_only_cancellation_and_shared_clock_contract() -> None:
    imports = _imports("app/usecases/brain_appraisal.py")
    assert "app.usecases.ports.cancellation.CancellationState" in imports
    assert "app.domain.contracts.time.Clock" in imports
    accesses = {
        node.attr for node in ast.walk(_tree("app/usecases/brain_appraisal.py"))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "cancellation"
    }
    assert accesses == {"cancelled"}
    assert "app.domain.contracts.time.Clock" in _imports("app/usecases/attention_binding.py")



def test_core_assembly_uses_application_persistence_bindings_not_adapters() -> None:
    for path in ("app/bootstrap/runtime_assembly.py", "app/bootstrap/core_components.py"):
        imports = _imports(path)
        assert "app.usecases.goal_persistence" in imports
        assert "app.usecases.memory_persistence" in imports
        assert "app.infrastructure.persistence.goal_binding" not in imports
        assert "app.infrastructure.persistence.memory_binding" not in imports


def test_cognition_imports_input_work_from_usecase_not_boot_entrypoint() -> None:
    imports = _imports("app/usecases/cognition_delivery.py")
    assert "app.usecases.brain_input_meaning.InputMeaningBrainWorkPayload" in imports
    assert not any(
        module == "app.application" or module.startswith("app.application.")
        for module in imports
    )


def test_appraisal_module_preserves_wide_port_contract() -> None:
    tree = _tree("app/usecases/cognition_delivery.py")
    owner = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "_AppraisalModule"
    )
    method = next(
        node for node in owner.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute"
    )
    annotations = {
        arg.arg: ast.unparse(arg.annotation)
        for arg in method.args.args if arg.annotation is not None
    }
    assert annotations["work"] == "BrainModuleWork"
    assert annotations["cancellation"] == "CancellationState"


def test_memory_evidence_reader_uses_only_published_read_operations() -> None:
    tree = _tree("app/usecases/memory_evidence.py")
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
        and node.func.value.attr == "memory"
    }
    assert calls == {"read_retrieval_publication", "read_semantic_assertion_publication"}


def test_all_domain_and_usecase_dependencies_point_inward() -> None:
    """全Domain・全UseCaseを一度の走査で検証し、個別の重複監査を持たない。"""
    violations: list[str] = []
    for path in sorted((ROOT / "app/domain").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for module in _imports(relative):
            if module == "app" or (
                module.startswith("app.")
                and module != "app.domain"
                and not module.startswith("app.domain.")
            ):
                violations.append(f"{relative}: {module}")
    for path in sorted((ROOT / "app/usecases").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for module in _imports(relative):
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in FORBIDDEN_OUTER
            ) or module.split(".")[0] in {"psycopg", "psycopg_pool", "openai", "PyQt6"}:
                violations.append(f"{relative}: {module}")
    assert not violations, "内向き依存の違反:\n" + "\n".join(violations)


def test_application_services_have_one_canonical_owner() -> None:
    assert DeepAppraisalInterpreter.__module__ == "app.usecases.appraisal"
    assert InputMeaningInterpreter.__module__ == "app.usecases.input_meaning"
    assert LLMRolePort is DomainLLMRolePort
    assert LLMRolePort.__module__ == "app.domain.llm.ports"
    assert PublicSpeechDelivery is CanonicalSpeechDelivery
    assert CanonicalSpeechDelivery.__module__ == "app.usecases.speech_delivery"
    assert GoalPlanner.__module__ == "app.usecases.goal_planning"
    assert BodyMotionPlanner.__module__ == "app.usecases.body_motion_planning"
    assert not is_dataclass(CoreApplication)



def test_legacy_and_canonical_kernel_public_types_are_identical() -> None:
    for name in kernel.__all__:
        assert getattr(legacy_scheduling, name) is getattr(kernel, name), name
