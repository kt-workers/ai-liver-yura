from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cloud_validation.character_response_lab import (
    CharacterResponseLabRequest,
    CharacterResponseLabService,
    LabSettings,
    _PRESETS,
    create_app,
)


def _settings() -> LabSettings:
    return LabSettings(
        mode="fake",
        model="",
        validator_model="",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=1.0,
        username="tester",
        password="secret",
    )


@pytest.mark.asyncio
async def test_fake_lab_runs_production_character_response_pipeline() -> None:
    service = CharacterResponseLabService(_settings())

    result = await service.analyze(CharacterResponseLabRequest())

    assert result["stopped_at"] == "character_response_pipeline"
    assert result["typed_target"] == {"type": "internal_state", "id": "joy"}
    assert result["generation_result"]["status"] == "validated"
    assert result["generation_result"]["attempts"] == 1
    assert result["final_response"]["speech"] == "検証用の応答です。"
    assert [call["role"] for call in result["model_calls"]] == [
        "character",
        "validator",
    ]
    assert "body_runtime" in result["not_executed"]
    assert "tts" in result["not_executed"]


@pytest.mark.asyncio
async def test_lab_can_expose_real_character_and_validator_prompts() -> None:
    service = CharacterResponseLabService(_settings())
    request = CharacterResponseLabRequest(include_prompts=True)

    result = await service.analyze(request)

    character_call, validator_call = result["model_calls"]
    assert "# Direct Internal State Answer Contract" in character_call["prompt"]
    assert '"id": "joy"' in character_call["prompt"]
    assert "# Direct Internal State Semantic Validation" in validator_call["prompt"]
    assert '"joy": 0.0' in validator_call["prompt"]
    assert '"curiosity": 0.61' in validator_call["prompt"]


def test_issue_210_presets_cover_target_specific_cases() -> None:
    assert set(_PRESETS) == {
        "joy_low_curiosity_high",
        "current_feeling_repeat",
        "anger_low",
        "current_desire",
    }
    targets = {
        key: preset["data"]["structured_input_meaning"]["target"]["id"]
        for key, preset in _PRESETS.items()
    }
    assert targets == {
        "joy_low_curiosity_high": "joy",
        "current_feeling_repeat": "current_feeling",
        "anger_low": "anger",
        "current_desire": "current_desire",
    }
    assert (
        _PRESETS["current_feeling_repeat"]["data"]["recent_speech_summary"]
    )


def test_http_lab_requires_auth_and_exposes_presets() -> None:
    client = TestClient(create_app(settings=_settings()))

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["stop_stage"] == "character_response_pipeline"

    unauthorized = client.get("/api/presets")
    assert unauthorized.status_code == 401

    authorized = client.get("/api/presets", auth=("tester", "secret"))
    assert authorized.status_code == 200
    assert "joy_low_curiosity_high" in authorized.json()


def test_index_explains_module_boundary() -> None:
    client = TestClient(create_app(settings=_settings()))

    response = client.get("/", auth=("tester", "secret"))

    assert response.status_code == 200
    assert "Character / Validator Lab" in response.text
    assert "全体Runtimeなし" in response.text
    assert "character_response_pipeline" in response.text
