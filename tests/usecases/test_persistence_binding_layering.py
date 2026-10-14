"""保存ユースケースが具体基盤を知らず、既存Portと同じ型を使うことを検証する。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from app.infrastructure.persistence.runtime import PostgresPersistenceRuntime
    from app.usecases.ports.goal_persistence import GoalPersistencePort
    from app.usecases.ports.memory_persistence import MemoryPersistencePort

    def _production_backend_satisfies_ports(
        backend: PostgresPersistenceRuntime,
    ) -> tuple[GoalPersistencePort, MemoryPersistencePort]:
        """全リポジトリのstrict Mypyで具体実装の代入互換性を検証する。"""
        return backend, backend

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "path",
    [
        "app/usecases/goal_persistence.py",
        "app/usecases/memory_persistence.py",
        "app/usecases/persistence_tasks.py",
        "app/usecases/ports/goal_persistence.py",
        "app/usecases/ports/memory_persistence.py",
    ],
)
def test_persistence_execution_dependencies_point_inward(path: str) -> None:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            modules = [node.module or ""]
        else:
            continue
        for module in modules:
            if module == "app" or module.startswith("app."):
                assert module.startswith(("app.domain.", "app.usecases.")), module
            assert module.split(".")[0] not in ("psycopg", "psycopg_pool", "openai", "PyQt6")


@pytest.mark.parametrize(
    "path,expected",
    [
        (
            "app/infrastructure/persistence/goal_binding.py",
            {"CoreGoalPersistenceBinding", "GoalPersistenceCommitResult"},
        ),
        (
            "app/infrastructure/persistence/memory_binding.py",
            {"CoreMemoryPersistenceBinding", "CoreMemoryOperation", "_reap"},
        ),
    ],
)
def test_old_binding_paths_only_reexport_the_application_owner(
    path: str, expected: set[str],
) -> None:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    names = {
        alias.asname
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.usecases.")
        for alias in node.names
        if alias.asname == alias.name
    }
    assert names == expected
    assert not any(isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                   for node in tree.body)


def test_goal_owner_identity_has_one_definition() -> None:
    codec = ast.parse((ROOT / "app/infrastructure/persistence/goal_snapshot_codec.py").read_text())
    goal = ast.parse((ROOT / "app/usecases/goal_persistence.py").read_text())
    for tree in (codec, goal):
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
            and any(isinstance(target, ast.Name) and target.id == "OWNER_ID"
                    for target in node.targets)
            for node in tree.body
        )
