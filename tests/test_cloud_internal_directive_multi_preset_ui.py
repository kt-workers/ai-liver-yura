from __future__ import annotations

from cloud_validation.internal_directive_lab_compact import _PRESETS
from cloud_validation.internal_directive_lab_reviewed import _REVIEWED_INDEX_HTML
from cloud_validation.internal_directive_lab_workspace import _WORKSPACE_INDEX_HTML


_ADDITIONAL_PRESET_KEYS = {
    "high_anger_direct_answer",
    "low_joy_high_engagement",
    "resolve_existing_knowledge_gap",
    "stop_ongoing_activity",
    "explain_activity",
    "high_interest_without_gap",
}


def test_high_curiosity_preset_has_matching_target_interest_and_gap() -> None:
    preset = _PRESETS["high_curiosity"]
    data = preset["data"]
    assert isinstance(data, dict)
    meaning = data["meaning"]
    state = data["state"]
    assert isinstance(meaning, dict)
    assert isinstance(state, dict)

    assert meaning["target"] == {
        "type": "topic",
        "id": "deep_sea_unknown_life",
    }
    related = state["related_knowledge"]
    assert isinstance(related, list)
    assert related == [
        {
            "target_type": "topic",
            "target_id": "deep_sea_unknown_life",
            "interest": 0.94,
            "known_facts": ["深海には未分類の生物が多く存在する"],
            "knowledge_gaps": [
                "未発見生物が多いと考えられている深度や環境"
            ],
        }
    ]


def test_additional_presets_are_registered_in_python_and_reviewed_html() -> None:
    assert _ADDITIONAL_PRESET_KEYS <= set(_PRESETS)
    assert len(_PRESETS) >= 13

    for key in _ADDITIONAL_PRESET_KEYS:
        assert f'"{key}":' in _REVIEWED_INDEX_HTML

    assert 'id="additional-internal-directive-presets"' in _REVIEWED_INDEX_HTML


def test_high_anger_preset_contains_anger_emotion() -> None:
    preset = _PRESETS["high_anger_direct_answer"]
    data = preset["data"]
    assert isinstance(data, dict)
    meaning = data["meaning"]
    state = data["state"]
    assert isinstance(meaning, dict)
    assert isinstance(state, dict)
    emotion = state["emotion"]
    assert isinstance(emotion, dict)

    assert meaning["target"] == {"type": "internal_state", "id": "anger"}
    assert emotion["anger"] == 0.86


def test_low_joy_high_engagement_preset_separates_emotion_and_motivation() -> None:
    preset = _PRESETS["low_joy_high_engagement"]
    data = preset["data"]
    assert isinstance(data, dict)
    state = data["state"]
    assert isinstance(state, dict)
    emotion = state["emotion"]
    motivation = state["motivation"]
    assert isinstance(emotion, dict)
    assert isinstance(motivation, dict)

    assert emotion["joy"] == 0.08
    assert emotion["amusement"] == 0.14
    assert motivation["engagement"] == 0.93


def test_resolve_gap_preset_has_existing_gap_and_answer_information() -> None:
    preset = _PRESETS["resolve_existing_knowledge_gap"]
    data = preset["data"]
    assert isinstance(data, dict)
    meaning = data["meaning"]
    state = data["state"]
    assert isinstance(meaning, dict)
    assert isinstance(state, dict)

    assert meaning["input_speech_act"] == "answer"
    assert meaning["information_provided"]
    related = state["related_knowledge"]
    assert isinstance(related, list)
    assert related[0]["knowledge_gaps"] == [
        "深海生物が高水圧へ適応できる仕組み"
    ]


def test_activity_operation_presets_use_registry_and_ongoing_state() -> None:
    stop_data = _PRESETS["stop_ongoing_activity"]["data"]
    explain_data = _PRESETS["explain_activity"]["data"]
    assert isinstance(stop_data, dict)
    assert isinstance(explain_data, dict)

    assert stop_data["ongoing"] is not None
    assert "stop" in stop_data["activities"][0]["operations"]
    assert stop_data["meaning"]["expected_response"] == "action"

    assert explain_data["ongoing"] is None
    assert "explain" in explain_data["activities"][0]["operations"]
    assert explain_data["meaning"]["expected_response"] == "action"


def test_high_interest_without_gap_has_no_knowledge_gap() -> None:
    preset = _PRESETS["high_interest_without_gap"]
    data = preset["data"]
    assert isinstance(data, dict)
    state = data["state"]
    assert isinstance(state, dict)
    related = state["related_knowledge"]
    assert isinstance(related, list)

    assert related[0]["interest"] == 0.96
    assert related[0]["knowledge_gaps"] == []
    assert state["drive"]["curiosity"] == 0.95
    assert state["motivation"]["engagement"] == 0.92


def _assert_export_is_below_run_and_before_result(html: str) -> None:
    run_position = html.index('id="run"')
    export_position = html.index('id="transferPanel"')
    result_position = html.index('id="resultPanel"')

    assert run_position < export_position < result_position
    assert html.count('id="transferPanel"') == 1
    assert html.count('id="exportLabText"') == 1


def test_workspace_places_export_below_run_button() -> None:
    _assert_export_is_below_run_and_before_result(_WORKSPACE_INDEX_HTML)


def test_reviewed_html_preserves_export_position() -> None:
    _assert_export_is_below_run_and_before_result(_REVIEWED_INDEX_HTML)
