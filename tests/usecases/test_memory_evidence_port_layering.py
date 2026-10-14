"""記憶根拠の接続口から保存先の具体実装を参照しない。"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from app.usecases.memory_persistence import CoreMemoryPersistenceBinding
    from app.usecases.ports.memory_evidence import MemoryEvidencePort

    def _binding_satisfies_memory_evidence_port(
        binding: CoreMemoryPersistenceBinding,
    ) -> MemoryEvidencePort:
        """全リポジトリのstrict Mypyで、保存ユースケースの代入互換性を確認する。"""
        return binding

ROOT = Path(__file__).resolve().parents[2]


def _tree(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)


@pytest.mark.parametrize(
    "path,prefixes",
    [
        ("app/domain/contracts/persistence.py", ("app.domain.",)),
        ("app/usecases/ports/memory_evidence.py", ("app.domain.", "app.usecases.")),
        ("app/usecases/memory_evidence.py", ("app.domain.", "app.usecases.")),
    ],
)
def test_memory_evidence_dependencies_point_inward(
    path: str, prefixes: tuple[str, ...],
) -> None:
    for node in ast.walk(_tree(path)):
        modules: tuple[str, ...]
        if isinstance(node, ast.Import):
            modules = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "この境界の依存先は絶対参照で明示する"
            modules = (node.module or "",)
        else:
            continue
        for module in modules:
            if module == "app" or module.startswith("app."):
                assert module.startswith(prefixes), f"{path}:{node.lineno}: {module}"


@pytest.mark.parametrize(
    "path,names",
    [
        (
            "app/infrastructure/persistence/contracts.py",
            ("PersistenceError", "PersistenceFailureCode"),
        ),
        ("app/infrastructure/persistence/runtime.py", ("PersistenceOperationResult",)),
    ],
)
def test_legacy_imports_explicitly_reexport_the_same_contract(
    path: str, names: tuple[str, ...],
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


def test_neutral_contract_and_port_load_without_storage_implementation() -> None:
    program = '''
import importlib.abc
import sys
sys.path.insert(0, sys.argv[1])

class RejectOuterImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefixes = ("app.infrastructure", "app.adapters", "app.composition", "psycopg")
        if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in prefixes):
            raise AssertionError("外側の実装を読み込もうとしました: " + fullname)
        return None

sys.meta_path.insert(0, RejectOuterImports())
from app.domain.contracts.persistence import PersistenceFailureCode, PersistenceOperationResult
from app.usecases.ports.memory_evidence import MemoryEvidencePort
assert PersistenceOperationResult(None, PersistenceFailureCode.CANCELLED).value is None
assert MemoryEvidencePort.__module__ == "app.usecases.ports.memory_evidence"
'''
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(ROOT)],
        cwd=ROOT, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_reader_uses_only_the_published_read_operations() -> None:
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
