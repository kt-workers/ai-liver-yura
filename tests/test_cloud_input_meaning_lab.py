from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from cloud_validation.input_meaning_lab import LabSettings, create_app


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


def test_health_is_public_and_reports_stop_stage() -> None:
    response = _client().get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["stop_stage"] == "input_meaning_interpreter"


def test_index_requires_basic_authentication() -> None:
    client = _client()

    unauthorized = client.get("/")
    authorized = client.get(
        "/",
        headers={"Authorization": _authorization()},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert "入力意味解析ラボ" in authorized.text


def test_fake_mode_returns_parsed_input_meaning_and_stops_before_later_roles() -> None:
    response = _client().post(
        "/api/input-meaning",
        headers={"Authorization": _authorization()},
        json={
            "text": "今は何をしたい気分ですか？",
            "current_topic": "現在の気分",
            "conversation_history": [],
            "include_prompt": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["mode"] == "fake"
    assert payload["parsed_response"]["input_speech_act"] == "question"
    assert payload["parsed_response"]["expected_response"] == "direct_answer"
    assert payload["stopped_at"] == "input_meaning_interpreter"
    assert payload["executed_later_stages"] == []
    assert "# ObservedInput" in payload["prompt"]


def test_history_limit_is_rejected() -> None:
    response = _client().post(
        "/api/input-meaning",
        headers={"Authorization": _authorization()},
        json={
            "text": "確認",
            "conversation_history": [
                {"role": "user", "text": f"turn-{index}"}
                for index in range(21)
            ],
        },
    )

    assert response.status_code == 400
    assert "最大20件" in response.json()["detail"]


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
