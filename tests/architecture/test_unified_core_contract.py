"""統合本体の単一起動・正規設定・構造を検証する。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_unified_cli_entry() -> None:
    module = ast.parse((ROOT / "app/application.py").read_text())
    functions = {
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"main", "run_core"} <= functions
    assert "build_core_application" not in functions
    from app.application import build_core_application as public_factory
    from app.bootstrap.cli_composition import build_core_application as canonical_factory

    assert public_factory is canonical_factory
    from app.application import build_core_runtime as public_runtime
    from app.application import build_persistent_core as public_persistent
    from app.bootstrap.runtime_assembly import build_core_runtime as canonical_runtime
    from app.bootstrap.runtime_assembly import build_persistent_core as canonical_persistent

    assert public_runtime is canonical_runtime
    assert public_persistent is canonical_persistent


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
    from app.bootstrap.core_components import compose_core_components

    placeholder = cast(Any, object())
    with pytest.raises(ValueError, match="認知・主観評価・注意・判断"):
        compose_core_components(placeholder, placeholder, placeholder, placeholder)


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
