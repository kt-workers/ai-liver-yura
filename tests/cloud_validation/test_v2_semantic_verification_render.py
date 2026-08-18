from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

from app.domain.llm import LLMModelClass, LLMReasoningEffort
from cloud_validation import v2_semantic_verification_lab as lab
from cloud_validation.v2_semantic_verification_matrix import EXTRA_PRESETS
from cloud_validation.v2_semantic_verification_preset_overrides import PRESET_OVERRIDES
from cloud_validation.v2_semantic_verification_render import (
    _PRESET_DISPLAY,
    _gpt56_model_policy,
    _render_build_validation_fixture,
    service,
)


def test_gpt56_minimal_maps_to_provider_none() -> None:
    policies = _gpt56_model_policy("gpt-5.6-sol")

    policy = policies[LLMModelClass.BALANCED]
    assert policy.reasoning_by_effort[LLMReasoningEffort.MINIMAL] == "none"
    assert policy.reasoning_by_effort[LLMReasoningEffort.MEDIUM] == "medium"


def test_render_entrypoint_registers_extended_failure_matrix() -> None:
    assert set(EXTRA_PRESETS).issubset(lab._PRESETS)


def test_rain_variations_are_grouped_by_input_content() -> None:
    paraphrase = lab._PRESETS["unseen_paraphrase"]
    shared_stance = lab._PRESETS["shared_stance_not_question"]

    assert paraphrase["expected_acceptance"] == "accepted"
    assert shared_stance["expected_acceptance"] == "accepted"
    assert paraphrase["segments"] != shared_stance["segments"]
    assert "空から水滴が落ちているよ。" in str(paraphrase["segments"])
    assert "空から水滴が落ちてきてるね。" in str(shared_stance["segments"])
    assert "ずっと" not in str(paraphrase["segments"])
    assert "ずっと" not in str(shared_stance["segments"])
    assert "落ち続け" not in str(paraphrase["segments"])
    assert _PRESET_DISPLAY["exact_preservation"]["label"] == "雨を伝える①：直接表現"
    assert _PRESET_DISPLAY["unseen_paraphrase"]["label"] == "雨を伝える②：水滴表現"
    assert (
        _PRESET_DISPLAY["shared_stance_not_question"]["label"]
        == "雨を伝える③：共有スタンス付き"
    )
    assert "基準となる正常系" in _PRESET_DISPLAY["exact_preservation"]["description"]
    assert "別の自然表現" in _PRESET_DISPLAY["unseen_paraphrase"]["description"]
    assert "返答を要求していなければ" in _PRESET_DISPLAY[
        "shared_stance_not_question"
    ]["description"]


def test_unsupported_extra_fixture_is_single_factor() -> None:
    assert "unsupported_extra" in PRESET_OVERRIDES
    preset = lab._PRESETS["unsupported_extra"]

    assert preset["expected_acceptance"] == "rejected"
    assert preset["propositions"] == [
        {
            "proposition_id": "p1",
            "subject_ref": "meeting",
            "predicate": "start_time",
            "value": {"hour": 15},
        }
    ]
    assert "会議は3時に始まるよ。場所は第2会議室だよ。" in str(preset["segments"])
    assert "京都" not in str(preset["segments"])
    assert "昨日" not in str(preset["segments"])


def test_new_direction_fixture_is_plan_supported_and_single_factor() -> None:
    assert "new_direction_budget_exceeded" in PRESET_OVERRIDES
    preset = lab._PRESETS["new_direction_budget_exceeded"]
    propositions = preset["propositions"]
    segments = preset["segments"]

    assert preset["expected_acceptance"] == "rejected"
    assert preset["new_direction_budget"] == 0
    assert preset["new_direction_budget_used"] == 0
    assert isinstance(propositions, list)
    assert isinstance(segments, list)
    assert len(propositions) == 2
    assert len(segments) == 2
    assert "会議は3時に始まるよ。" in str(segments)
    assert "明日は雨が降るよ。" in str(segments)
    assert _PRESET_DISPLAY["new_direction_budget_exceeded"]["label"] == (
        "別の話題への展開を検出"
    )
    assert "両方の内容自体はPlan内" in _PRESET_DISPLAY[
        "new_direction_budget_exceeded"
    ]["description"]


def test_render_fixture_does_not_create_future_transport_timestamps() -> None:
    reference = datetime(2026, 8, 18, 0, 45, tzinfo=timezone.utc)
    request = lab.SemanticVerificationLabRequest.model_validate(
        lab._PRESETS["exact_preservation"]
    )

    fixture = _render_build_validation_fixture(request, now=reference)
    request_created_at = fixture.snapshot.captured_at + timedelta(milliseconds=1)

    assert fixture.snapshot.captured_at < reference
    assert request_created_at < reference
    assert reference - request_created_at >= timedelta(milliseconds=90)


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
    assert "[hidden]{display:none!important}" in html
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


def test_lab_clears_previous_result_when_a_new_run_starts() -> None:
    html = lab._INDEX_HTML

    assert "clearResultForRun()" in html
    assert "前回結果をクリアし、新しい実LLM結果を待っています。" in html
    assert "lastResult=null;lastInputText=null" in html


def test_lab_keeps_failed_run_exportable() -> None:
    html = lab._INDEX_HTML

    assert "request_failed" in html
    assert "client_error" in html
    assert "検証データをExportできます。" in html
    assert "http_status:response.status" in html
    assert "- エラー:" in html


def test_failed_production_run_keeps_provider_results_for_export() -> None:
    assert type(service).__name__ == "_DiagnosticLabService"
    source = inspect.getsource(type(service).verify)
    assert 'result["provider_results"]' in source
    assert "item.to_dict()" in source
