from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from cloud_validation.internal_directive_lab_compact import LabSettings, create_app


def _authorization(username: str = "tester", password: str = "secret") -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def _client(*, mode: str = "fake") -> TestClient:
    settings = LabSettings(
        mode=mode,
        model="test-model" if mode == "live" else "",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=1.0,
        username="tester",
        password="secret",
    )
    return TestClient(create_app(settings=settings))


def _request_payload(*, include_prompt: bool = False) -> dict[str, object]:
    return {
        "structured_input_meaning": {
            "input_speech_act": "question",
            "primary_intent": "ask_current_feeling",
            "expected_response": "direct_answer",
            "target": {"type": "internal_state", "id": "current_feeling"},
            "entities": [],
            "references": [],
            "information_provided": [],
            "negated": False,
            "hypothetical": False,
            "past_reference": False,
            "conversation_phase_signal": "continue",
            "confidence": 0.98,
            "reason": "現在の気分への直接質問",
        },
        "internal_state": {
            "emotion": {"joy": 0.5, "calm": 0.8},
            "drive": {"curiosity": 0.6},
            "relationship": {},
            "motivation": {},
            "moral": {},
            "situation": {"current_topic": "現在の気分"},
            "memory": {},
            "related_knowledge": [],
            "last_activity_result": None,
        },
        "ongoing_activity": None,
        "available_activities": [
            {
                "activity_type": "conversation",
                "operations": ["discuss", "explain"],
            }
        ],
        "character_profile": {
            "name": "ゆら",
            "existence": {
                "physical_capabilities": ["物理的な身体を持たない"],
                "experience_boundaries": ["根拠のない実体験を語らない"],
            },
        },
        "include_prompt": include_prompt,
    }


def test_health_is_public_and_reports_stop_stage() -> None:
    response = _client().get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["stop_stage"] == "internal_directive_planner"


def test_index_requires_basic_authentication() -> None:
    client = _client()

    unauthorized = client.get("/")
    authorized = client.get(
        "/",
        headers={"Authorization": _authorization()},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert "内部指示器ラボ" in authorized.text


def test_index_exposes_gui_and_json_editing_modes() -> None:
    response = _client().get(
        "/",
        headers={"Authorization": _authorization()},
    )

    assert response.status_code == 200
    html = response.text
    assert "GUI入力" in html
    assert "JSON入力" in html
    assert 'type="range"' in html
    assert 'id="stateOverview"' in html
    assert 'id="metricGroups"' in html
    assert 'id="addActivity"' in html
    assert 'data-apply-json="state"' in html


def test_index_hides_duplicate_horizontal_meters() -> None:
    response = _client().get(
        "/",
        headers={"Authorization": _authorization()},
    )

    assert response.status_code == 200
    html = response.text
    assert 'id="compact-metric-display"' in html
    assert ".meter-track { display: none !important; }" in html
    assert "スライダーと数値欄が連動します。" in html
    assert "数値はメーターにも反映されます。" not in html
    assert 'id="stateOverview"' in html


def test_fake_mode_returns_internal_directive_and_stops_before_later_stages() -> None:
    response = _client().post(
        "/api/internal-directive",
        headers={"Authorization": _authorization()},
        json=_request_payload(include_prompt=True),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["mode"] == "fake"
    assert payload["parsed_response"]["response_mode"] == "answer"
    assert payload["parsed_response"]["question_budget"] == 0
    assert payload["stopped_at"] == "internal_directive_planner"
    assert payload["executed_later_stages"] == []
    assert "internal_directive_validator" in payload["not_executed"]
    assert "# DirectiveInput" in payload["prompt"]
    assert "Raw User Text" in payload["prompt"]


def test_invalid_structured_input_meaning_is_rejected() -> None:
    payload = _request_payload()
    payload["structured_input_meaning"] = {
        "input_speech_act": "unknown",
        "primary_intent": "broken",
    }

    response = _client().post(
        "/api/internal-directive",
        headers={"Authorization": _authorization()},
        json=payload,
    )

    assert response.status_code == 400
    assert "StructuredInputMeaning契約" in response.json()["detail"]


def test_missing_auth_configuration_fails_closed() -> None:
    settings = LabSettings(
        mode="fake",
        model="",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=1.0,
        username="",
        password="",
    )
    client = TestClient(create_app(settings=settings))

    response = client.get("/")

    assert response.status_code == 503
