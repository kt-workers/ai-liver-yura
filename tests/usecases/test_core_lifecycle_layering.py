"""分離した起動・停止と構成の責務を、入口や外側の実装へ戻さない。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _tree(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)


def _imports(tree: ast.Module) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "分離した境界の依存先は絶対参照で明示する"
            modules.append(node.module or "")
    return modules


@pytest.mark.parametrize(
    "path",
    [
        "app/usecases/core_lifecycle.py",
        "app/usecases/resource_cleanup.py",
        "app/usecases/ports/core_lifecycle.py",
        "app/usecases/task_cleanup.py",
    ],
)
def test_core_lifecycle_dependencies_point_inward(path: str) -> None:
    violations = [
        module for module in _imports(_tree(path))
        if (module == "app" or module.startswith("app."))
        and not module.startswith(("app.domain.", "app.usecases."))
    ]
    assert not violations, f"{path}: {violations}"


@pytest.mark.parametrize(
    "path",
    [
        "app/bootstrap/core_components.py",
        "app/composition/system_cognition_configuration.py",
    ],
)
def test_core_factories_do_not_call_back_into_entrypoint(path: str) -> None:
    assert "app.application" not in _imports(_tree(path))


def test_entrypoint_does_not_implement_core_execution_or_assembly() -> None:
    definitions = {
        node.name for node in _tree("app/application.py").body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert definitions.isdisjoint(
        {"CoreComponents", "start_core", "stop_core", "_close_core_memory", "_compose_core"}
    )


def test_core_components_are_data_not_a_lifecycle_service() -> None:
    components = next(
        node for node in _tree("app/bootstrap/core_components.py").body
        if isinstance(node, ast.ClassDef) and node.name == "CoreComponents"
    )
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in components.body
    )


def test_composition_facade_does_not_own_tasks_or_resource_cleanup() -> None:
    tree = _tree("app/composition/system_cognition_configuration.py")
    assert not any(
        isinstance(node, ast.ClassDef) and node.name == "_OwnedResources" for node in tree.body
    )
    facade = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "CoreApplication"
    )
    for node in ast.walk(facade):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {
                "create_task", "shield", "wait_for", "_start_task", "_stop_task",
            }
    methods = {node.name for node in facade.body if isinstance(node, ast.AsyncFunctionDef)}
    assert methods == {"start", "stop"}


@pytest.mark.parametrize("path", ["app/application.py", "app/bootstrap/core_components.py"])
def test_core_assembly_uses_inner_persistence_bindings(path: str) -> None:
    imports = _imports(_tree(path))
    assert "app.usecases.goal_persistence" in imports
    assert "app.usecases.memory_persistence" in imports
    assert "app.infrastructure.persistence.goal_binding" not in imports
    assert "app.infrastructure.persistence.memory_binding" not in imports
