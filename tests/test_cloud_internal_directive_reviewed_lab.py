from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from cloud_validation.internal_directive_lab_reviewed import (
    LabSettings,
    _REVIEWED_INDEX_HTML,
    create_app,
)
from cloud_validation.internal_directive_lab_compact import _PRESETS


def _authorization() -> str:
    token = base64.b64encode(b"tester:secret").decode()
    return f"Basic {token}"


def _client() -> TestClient:
    return TestClient(
        create_app(
            settings=LabSettings(
                mode="fake",
                model="",
                api_key_env="OPENAI_API_KEY",
                timeout_seconds=1.0,
                username="tester",
                password="secret",
            )
        )
    )


def test_existence_boundary_preset_marks_yesterday_as_past_reference() -> None:
    data = _PRESETS["existence_boundary"]["data"]
    assert isinstance(data, dict)
    meaning = data["meaning"]
    assert isinstance(meaning, dict)

    assert meaning["target"] == {
        "type": "character_experience",
        "id": "yesterday_outing",
    }
    assert meaning["past_reference"] is True


def test_high_curiosity_preset_keeps_structured_related_knowledge() -> None:
    data = _PRESETS["high_curiosity"]["data"]
    assert isinstance(data, dict)
    state = data["state"]
    assert isinstance(state, dict)
    related_knowledge = state["related_knowledge"]

    assert related_knowledge == [
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


def test_reviewed_html_contains_corrected_preset_and_workspace_controls() -> None:
    assert '"yesterday_outing"' in _REVIEWED_INDEX_HTML
    assert '"past_reference":true' in _REVIEWED_INDEX_HTML
    assert 'id="exportLabText"' in _REVIEWED_INDEX_HTML
    assert "setupLabCollapsibleSections()" in _REVIEWED_INDEX_HTML


def test_reviewed_html_preserves_related_knowledge_objects() -> None:
    assert 'placeholder="1行につきJSONオブジェクト1件"' in _REVIEWED_INDEX_HTML
    assert "JSON.stringify(item)).join('\\n')" in _REVIEWED_INDEX_HTML
    assert (
        ".map(line => { try { return JSON.parse(line); } catch { return line; } });"
        in _REVIEWED_INDEX_HTML
    )
    assert "lines(state.related_knowledge);" not in _REVIEWED_INDEX_HTML
    assert "model.state.related_knowledge = parseLines(" in _REVIEWED_INDEX_HTML
    assert '"target_type":"topic"' in _REVIEWED_INDEX_HTML
    assert '"target_id":"deep_sea_unknown_life"' in _REVIEWED_INDEX_HTML
    assert '"knowledge_gaps":["未発見生物が多いと考えられている深度や環境"]' in (
        _REVIEWED_INDEX_HTML
    )
    assert "[object Object]" not in _REVIEWED_INDEX_HTML


def test_reviewed_html_collapses_input_sections_by_default() -> None:
    assert "body.className = 'editor-collapsible-body hidden';" in (
        _REVIEWED_INDEX_HTML
    )
    assert "button.setAttribute('aria-expanded', 'false');" in (
        _REVIEWED_INDEX_HTML
    )
    assert "button.setAttribute('aria-label', `${label}を展開する`);" in (
        _REVIEWED_INDEX_HTML
    )
    assert "button.textContent = '展開する';" in _REVIEWED_INDEX_HTML
    assert "overview.dataset.alwaysVisible = 'true';" in _REVIEWED_INDEX_HTML


def test_reviewed_app_serves_corrected_complete_html() -> None:
    response = _client().get(
        "/",
        headers={"Authorization": _authorization()},
    )

    assert response.status_code == 200
    assert '"past_reference":true' in response.text
    assert "ChatGPT用テキストをExport" in response.text
    assert "body.className = 'editor-collapsible-body hidden';" in response.text
    assert "button.textContent = '展開する';" in response.text
    assert "JSON.stringify(item)).join('\\n')" in response.text
    assert "[object Object]" not in response.text
