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


def test_reviewed_html_contains_corrected_preset_and_workspace_controls() -> None:
    assert '"yesterday_outing"' in _REVIEWED_INDEX_HTML
    assert '"past_reference":true' in _REVIEWED_INDEX_HTML
    assert 'id="exportLabText"' in _REVIEWED_INDEX_HTML
    assert "setupLabCollapsibleSections()" in _REVIEWED_INDEX_HTML


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
