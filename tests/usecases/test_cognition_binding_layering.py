"""認知の実行責務を構成処理や具体Runtimeへ戻さない。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOVED = (
    ("app/composition/input_reference_context.py", "app/usecases/input_reference_context.py"),
    ("app/composition/appraisal.py", "app/usecases/brain_appraisal.py"),
    ("app/composition/attention.py", "app/usecases/attention_binding.py"),
)
INPUT_CONTRACT = "app/usecases/ports/brain_work.py"
CONSUMERS = (
    "app/bootstrap/core_components.py",
    "app/composition/cognition_configuration.py",
    "app/composition/cognition.py",
)


def _tree(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)


def _imports(path: str) -> tuple[str, ...]:
    package = path.removesuffix(".py").replace("/", ".").rsplit(".", 1)[0]
    modules: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = ""
            if node.level:
                parts = package.split(".")
                assert node.level <= len(parts)
                prefix = ".".join(parts[: len(parts) - node.level + 1])
            module = ".".join(part for part in (prefix, node.module or "") if part)
            modules.append(module)
            modules.extend(module + "." + alias.name for alias in node.names)
    return tuple(modules)


@pytest.mark.parametrize("path", [new for _, new in MOVED] + [INPUT_CONTRACT])
def test_cognition_execution_imports_only_inward(path: str) -> None:
    forbidden = (
        "app.application",
        "app.bootstrap",
        "app.composition",
        "app.config",
        "app.infrastructure",
        "app.adapters",
        "app.subsystems",
    )
    violations = [
        module for module in _imports(path)
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
    ]
    assert not violations, f"{path}: {violations}"


@pytest.mark.parametrize("old,new", MOVED)
def test_old_entrypoint_only_reexports_the_same_owned_definitions(old: str, new: str) -> None:
    target = new.removesuffix(".py").replace("/", ".")
    definitions = {
        node.name for node in _tree(new).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    exported: set[str] = set()
    for node in _tree(old).body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            assert isinstance(node.value.value, str)
            continue
        assert isinstance(node, ast.ImportFrom), "旧入口に実行処理を残さない"
        assert node.module == target and node.level == 0
        for alias in node.names:
            assert alias.asname == alias.name and alias.name != "*"
            exported.add(alias.name)
    assert exported == definitions


@pytest.mark.parametrize("path", CONSUMERS)
def test_primary_consumers_use_the_new_owners_directly(path: str) -> None:
    old_modules = {old.removesuffix(".py").replace("/", ".") for old, _ in MOVED}
    assert not (set(_imports(path)) & old_modules)


def test_appraisal_reads_work_contract_not_scheduler_implementation() -> None:
    imports = _imports("app/usecases/brain_appraisal.py")
    assert "app.usecases.ports.brain_work.BrainModuleWork" in imports
    assert not any(
        module.startswith("app.usecases.brain_integration_runtime") for module in imports
    )


def test_appraisal_cancellation_input_is_read_only() -> None:
    path = "app/usecases/brain_appraisal.py"
    assert "app.usecases.ports.cancellation.CancellationState" in _imports(path)
    accesses = {
        node.attr for node in ast.walk(_tree(path))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "cancellation"
    }
    assert accesses == {"cancelled"}


@pytest.mark.parametrize(
    "path", ["app/usecases/brain_appraisal.py", "app/usecases/attention_binding.py"]
)
def test_clock_comes_from_the_shared_inward_contract(path: str) -> None:
    assert "app.domain.contracts.time.Clock" in _imports(path)


def test_cognition_does_not_get_input_work_from_boot_entrypoint() -> None:
    imports = _imports("app/composition/cognition.py")
    assert "app.usecases.brain_input_meaning.InputMeaningBrainWorkPayload" in imports
    assert not any(
        module == "app.application" or module.startswith("app.application.")
        for module in imports
    )


def test_appraisal_subclass_does_not_narrow_the_input_contracts() -> None:
    tree = _tree("app/composition/cognition.py")
    owner = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "_AppraisalModule"
    )
    method = next(
        node for node in owner.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute"
    )
    types = {arg.arg: ast.unparse(arg.annotation) for arg in method.args.args if arg.annotation}
    assert types["work"] == "BrainModuleWork"
    assert types["cancellation"] == "CancellationState"


@pytest.mark.parametrize("path", [new for _, new in MOVED] + [INPUT_CONTRACT])
def test_moved_execution_uses_python_310_syntax(path: str) -> None:
    ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path, feature_version=(3, 10))
