"""旧Minimum/S2製品構成を廃止したことを静的に検証する。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_unified_cli_entry_has_no_staged_product_mode() -> None:
    module = ast.parse((ROOT / "app/application.py").read_text())
    functions = {
        node.name: node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "main" in functions
    assert "build_core_application" in functions
    assert "run_core" in functions
    source = ast.unparse(module)
    assert "build_s2_production_core" not in source
    assert "build_minimum_core" not in source
    assert "--s2-production" not in source


def test_retired_product_configs_are_absent() -> None:
    retired = (
        "app/config/minimum_brain.py",
        "app/config/cognition_s2.py",
        "app/config/s2_contracts.py",
        "app/composition/s2_provider.py",
        "resources/config/v2/minimum_brain.yaml",
        "resources/config/v2/cognition_s2.yaml",
        "resources/config/v2/provider_deployment_s2.yaml",
    )
    assert all(not (ROOT / path).exists() for path in retired)


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
    assert "brain.register_module(BrainIntegrationModule.INPUT_MEANING, bridge)" not in source

def test_no_resources_directory_and_settings_are_canonical() -> None:
    assert not (ROOT / "resources").exists()
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
