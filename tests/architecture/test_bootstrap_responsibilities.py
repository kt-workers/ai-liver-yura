"""統合本体の構成コード分離と禁止された旧構成の残存を検査する。"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.bootstrap import composition_contracts, composition_snapshot, core_application
from app.bootstrap import system_cognition_configuration as system

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = ("app", "tests", "config", "tools")
RETIRED_CONSTRUCTION = re.compile(r"(?<![a-zA-Z0-9_])[sS]\\x32(?![a-zA-Z0-9_])")
INSTRUCTION_FRAGMENTS = ("ここの", "機械的に削除", "全体の辻褄", "辻褄がおかしく")


def test_composition_contract_types_have_one_definition() -> None:
    for name in (
        "CoreRunIdentity",
        "ComponentBindings",
        "SubsystemBinding",
        "LLMConnectionBinding",
        "SystemCompositionSnapshot",
    ):
        canonical = getattr(composition_contracts, name)
        assert getattr(system, name) is canonical
        assert canonical.__module__ == composition_contracts.__name__


def test_application_owner_and_snapshot_projection_are_separate() -> None:
    assert system.CoreApplication is core_application.CoreApplication
    assert system._snapshot is composition_snapshot._snapshot


def test_assembly_module_contains_no_duplicate_contract_or_lifecycle_class() -> None:
    assembly = ROOT / "app/bootstrap/system_cognition_configuration.py"
    source = assembly.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not any(isinstance(node, ast.ClassDef) for node in tree.body)
    assert any(
        isinstance(node, ast.AsyncFunctionDef) and node.name == "compose_core"
        for node in tree.body
    )


def test_product_code_has_no_retired_package_or_embedded_edit_instructions() -> None:
    for folder in SOURCE_DIRS:
        for path in (ROOT / folder).rglob("*"):
            if not path.is_file() or path.suffix not in (".py", ".yaml", ".yml", ".json"):
                continue
            # この静的検査の照合文字列自体は検査の対象に含めない。
            if path.name == "test_bootstrap_responsibilities.py":
                continue
            text = path.read_text(encoding="utf-8")
            if folder == "app":
                assert "app.composition." not in text, str(path)
                assert "resources/" not in text, str(path)
            assert RETIRED_CONSTRUCTION.search(text) is None, str(path)
            assert not any(fragment in text for fragment in INSTRUCTION_FRAGMENTS), str(path)
