from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.llm import LLMModelClass, LLMReasoningEffort
from cloud_validation import v2_semantic_verification_lab as lab
from cloud_validation.v2_semantic_verification_matrix import EXTRA_PRESETS
from cloud_validation.v2_semantic_verification_render import (
    _PRESET_DISPLAY,
    _gpt56_model_policy,
    _render_build_validation_fixture,
)


def test_gpt56_minimal_maps_to_provider_none() -> None:
    policies = _gpt56_model_policy("gpt-5.6-sol")

    policy = policies[LLMModelClass.BALANCED]
    assert policy.reasoning_by_effort[LLMReasoningEffort.MINIMAL] == "none"
    assert policy.reasoning_by_effort[LLMReasoningEffort.MEDIUM] == "medium"


def test_render_entrypoint_registers_extended_failure_matrix() -> None:
    assert set(EXTRA_PRESETS).issubset(lab._PRESETS)


def test_render_fixture_timeline_finishes_before_live_request_time() -> None:
    reference = datetime(2026, 8, 18, 0, 45, tzinfo=timezone.utc)
    request = lab.SemanticVerificationLabRequest.model_validate(
        lab._PRESETS["exact_preservation"]
    )

    fixture = _render_build_validation_fixture(request, now=reference)
    request_created_at = fixture.snapshot.captured_at + timedelta(milliseconds=1)

    assert fixture.snapshot.captured_at < reference
    assert request_created_at < reference


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
    assert "__WORKSPACE_STYLE__" not in html
    assert "__WORKSPACE_SCRIPT__" not in html
    assert "__PRESET_DISPLAY__" not in html
