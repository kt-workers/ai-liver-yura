"""統合本体の単一起動・正規設定・構造を検証する。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_unified_cli_entry() -> None:
    module = ast.parse((ROOT / "app/application.py").read_text())
    functions = {
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"main", "build_core_application", "run_core"} <= functions


def test_legacy_layout_directories_are_absent() -> None:
    assert not (ROOT / "resources").exists()
    assert not (ROOT / "app/composition").exists()


def test_full_core_config_is_the_only_product_config() -> None:
    config = (ROOT / "config/core.yaml").read_text()
    assert "activation_id: yura.core.explicit" in config
    assert "appraisal_config:" in config
    assert "executive_config:" in config
    assert "attention_policy:" in config
    assert "llm_connections:" in config


def test_core_components_reject_partial_brain_registration() -> None:
    source = (ROOT / "app/bootstrap/core_components.py").read_text()
    assert "統合本体には認知・主観評価・注意・判断の構成が必須" in source


def test_settings_are_in_config_directory() -> None:
    for path in (
        "config/core.yaml",
        "config/appraisal.yaml",
        "config/executive.yaml",
        "config/character/yura.yaml",
        "config/user.yaml",
        "config/profiles/speech/conservative.yaml",
        "config/gui_admin.yaml",
    ):
        assert (ROOT / path).is_file()
