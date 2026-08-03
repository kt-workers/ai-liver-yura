from __future__ import annotations

from cloud_validation.internal_directive_lab_compact import _PRESETS
from cloud_validation.internal_directive_lab_reviewed import _REVIEWED_INDEX_HTML
from cloud_validation.internal_directive_lab_workspace import _WORKSPACE_INDEX_HTML


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
