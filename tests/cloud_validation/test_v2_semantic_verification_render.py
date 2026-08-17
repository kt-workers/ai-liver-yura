from __future__ import annotations

from app.domain.llm import LLMModelClass, LLMReasoningEffort
from cloud_validation import v2_semantic_verification_lab as lab
from cloud_validation.v2_semantic_verification_matrix import EXTRA_PRESETS
from cloud_validation.v2_semantic_verification_render import (
    _PRESET_DISPLAY,
    _gpt56_model_policy,
)


def test_gpt56_minimal_maps_to_provider_none() -> None:
    policies = _gpt56_model_policy("gpt-5.6-sol")

    policy = policies[LLMModelClass.BALANCED]
    assert policy.reasoning_by_effort[LLMReasoningEffort.MINIMAL] == "none"
    assert policy.reasoning_by_effort[LLMReasoningEffort.MEDIUM] == "medium"


def test_render_entrypoint_registers_extended_failure_matrix() -> None:
    assert set(EXTRA_PRESETS).issubset(lab._PRESETS)


def test_every_render_preset_has_japanese_display_metadata() -> None:
    assert set(lab._PRESETS) == set(_PRESET_DISPLAY)
    for preset_id, metadata in _PRESET_DISPLAY.items():
        assert metadata["label"] != preset_id
        assert metadata["description"]
        assert any(ord(char) > 127 for char in metadata["label"])


def test_lab_html_uses_fixed_workspace_and_collapsed_detail_sections() -> None:
    html = lab._INDEX_HTML

    assert "height:100vh" in html
    assert "overflow:hidden" in html
    assert "検証プリセット" in html
    assert "選択内容を適用" in html
    assert "実LLMで検証" in html
    assert "検証データをExport" in html
    assert "本番検証結果" in html
    assert '<details><summary>Role A' in html
    assert '<details open>' not in html
