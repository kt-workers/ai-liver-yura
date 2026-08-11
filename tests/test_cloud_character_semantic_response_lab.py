from __future__ import annotations

import pytest

from cloud_validation import character_response_lab as base
from cloud_validation.character_semantic_response_lab import (
    CharacterSemanticResponseLabService,
)


def _settings() -> base.LabSettings:
    return base.LabSettings(
        mode="fake",
        model="fake-character",
        validator_model="fake-validator",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=10.0,
        username="tester",
        password="secret",
    )


@pytest.mark.asyncio
async def test_semantic_lab_exports_new_pipeline_boundaries() -> None:
    service = CharacterSemanticResponseLabService(_settings())

    result = await service.analyze(base.CharacterResponseLabRequest())

    plan = result["semantic_utterance_plan"]
    assert isinstance(plan, dict)
    assert plan["target"] == {"type": "internal_state", "id": "joy"}
    propositions = plan["propositions"]
    assert isinstance(propositions, list)
    assert propositions[0]["predicate"] == "joy"
    assert propositions[0]["state"] == "absent"

    semantic_validation = result["semantic_validation"]
    assert isinstance(semantic_validation, dict)
    assert semantic_validation["accepted"] is True
    assert semantic_validation["reason"] == "semantic_plan_consistent"

    character = result["character_utterance"]
    assert isinstance(character, dict)
    assert character["semantic_realizations"] == ["proposition:0:joy"]

    realization = result["realization_validation"]
    assert isinstance(realization, dict)
    assert realization["accepted"] is True
    assert realization["reason"] == "semantic_realization_consistent"


@pytest.mark.asyncio
async def test_semantic_lab_exports_final_regeneration_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _synthetic_analyze(
        _self: base.CharacterResponseLabService,
        _request: base.CharacterResponseLabRequest,
    ) -> dict[str, object]:
        return {
            "response_context": {
                "memory": {
                    "semantic_utterance_plan": {"speech_act": "direct_answer"},
                    "semantic_validation": {
                        "accepted": True,
                        "reason": "semantic_plan_consistent",
                        "differences": [],
                    },
                }
            },
            "model_calls": [
                {
                    "role": "character_language_realizer",
                    "parsed_response": {"speech": "少し気になります。"},
                    "context_keys": ["semantic_boundary"],
                    "semantic_boundary": True,
                },
                {
                    "role": "character_realization_validator",
                    "parsed_response": {
                        "accepted": False,
                        "reason": "semantic_facet_validation_failed",
                        "differences": ["unsupported_intensity_markers:少し"],
                    },
                    "context_keys": ["semantic_boundary"],
                    "semantic_boundary": True,
                },
                {
                    "role": "character_language_realizer",
                    "parsed_response": {"speech": "気になります。"},
                    "context_keys": ["semantic_boundary"],
                    "semantic_boundary": True,
                },
                {
                    "role": "character_realization_validator",
                    "parsed_response": {
                        "accepted": True,
                        "reason": "semantic_realization_consistent",
                        "differences": [],
                    },
                    "context_keys": ["semantic_boundary"],
                    "semantic_boundary": True,
                },
            ],
            "final_response": {
                "speech": "気になります。",
                "linguistic_performance": {"phrasing": ["気になります。"]},
                "semantic_realizations": ["proposition:0:current_desire"],
            },
        }

    monkeypatch.setattr(base.CharacterResponseLabService, "analyze", _synthetic_analyze)
    service = CharacterSemanticResponseLabService(_settings())

    result = await service.analyze(base.CharacterResponseLabRequest())

    assert result["character_utterance"] == {"speech": "気になります。"}
    realization = result["realization_validation"]
    assert isinstance(realization, dict)
    assert realization["accepted"] is True
    assert realization["reason"] == "semantic_realization_consistent"


@pytest.mark.asyncio
async def test_semantic_lab_records_sanitized_character_and_validator_model_boundaries() -> None:
    service = CharacterSemanticResponseLabService(_settings())

    result = await service.analyze(base.CharacterResponseLabRequest())

    character_boundary = result["character_model_boundary"]
    validator_boundary = result["validator_model_boundary"]
    assert isinstance(character_boundary, dict)
    assert isinstance(validator_boundary, dict)
    assert character_boundary["role"] == "character_language_realizer"
    assert validator_boundary["role"] == "character_realization_validator"
    assert character_boundary["semantic_boundary"] is True
    assert validator_boundary["semantic_boundary"] is True

    forbidden_keys = {
        "user_input",
        "response_context",
        "event_payload",
        "activity_execution_result",
        "ongoing_activity",
        "emotion",
        "drive",
    }
    assert forbidden_keys.isdisjoint(character_boundary["context_keys"])
    assert forbidden_keys.isdisjoint(validator_boundary["context_keys"])


@pytest.mark.asyncio
async def test_semantic_lab_preserves_upstream_raw_snapshot_for_diagnostics_only() -> None:
    request = base.CharacterResponseLabRequest(
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.0,
                    "calm": 0.58,
                }
            }
        },
        drive={"curiosity": 0.82, "engagement": 0.78},
    )
    service = CharacterSemanticResponseLabService(_settings())

    result = await service.analyze(request)

    # Labの診断snapshotには上流stateを残すが、上のboundary testどおりLLM callには渡さない。
    response_context = result["response_context"]
    assert response_context["emotion"]["current"]["reactive"]["joy"] == 0.0
    assert response_context["drive"]["curiosity"] == 0.82
    assert result["semantic_utterance_plan"]["propositions"][0]["state"] == "absent"


def test_render_module_exposes_same_existing_lab_request_schema() -> None:
    request = base.CharacterResponseLabRequest()

    assert request.user_input == "楽しい？"
    assert request.structured_input_meaning["target"] == {
        "type": "internal_state",
        "id": "joy",
    }


def _preset_request(key: str) -> base.CharacterResponseLabRequest:
    preset = base._PRESETS[key]
    data = preset["data"]
    assert isinstance(data, dict)
    return base.CharacterResponseLabRequest(**data)


@pytest.mark.asyncio
async def test_extended_presets_cover_distinct_production_semantic_shapes() -> None:
    service = CharacterSemanticResponseLabService(_settings())

    joy_high = await service.analyze(_preset_request("extended_joy_high"))
    joy_proposition = joy_high["semantic_utterance_plan"]["propositions"][0]
    assert joy_proposition["predicate"] == "joy"
    assert joy_proposition["state"] == "high"
    assert joy_proposition["certainty"] == "high"
    assert joy_proposition["concept"] is None

    sadness_unknown = await service.analyze(
        _preset_request("extended_sadness_unknown_low")
    )
    sadness_unknown_proposition = sadness_unknown["semantic_utterance_plan"][
        "propositions"
    ][0]
    assert sadness_unknown_proposition["predicate"] == "sadness"
    assert sadness_unknown_proposition["state"] == "unknown"
    assert sadness_unknown_proposition["certainty"] == "low"
    assert sadness_unknown_proposition["evidence_refs"] == []

    sadness_explicit_unknown = await service.analyze(
        _preset_request("extended_sadness_explicit_unknown")
    )
    sadness_explicit_proposition = sadness_explicit_unknown[
        "semantic_utterance_plan"
    ]["propositions"][0]
    assert sadness_explicit_proposition["predicate"] == "sadness"
    assert sadness_explicit_proposition["state"] == "unknown"
    assert sadness_explicit_proposition["certainty"] == "high"
    assert sadness_explicit_proposition["evidence_refs"] == [
        "emotion.current.reactive.sadness"
    ]

    feeling_mixed = await service.analyze(
        _preset_request("extended_current_feeling_mixed")
    )
    mixed_propositions = feeling_mixed["semantic_utterance_plan"]["propositions"]
    assert mixed_propositions[0]["predicate"] == "current_feeling"
    assert mixed_propositions[0]["state"] == "overview"
    assert mixed_propositions[0]["certainty"] == "high"
    mixed_states = {
        item["predicate"]: item["state"] for item in mixed_propositions[1:]
    }
    assert mixed_states == {
        "joy": "high",
        "anger": "moderate",
        "calm": "low",
        "amusement": "absent",
    }

    desire_unknown = await service.analyze(
        _preset_request("extended_current_desire_unknown")
    )
    desire_unknown_proposition = desire_unknown["semantic_utterance_plan"][
        "propositions"
    ][0]
    assert desire_unknown_proposition["predicate"] == "current_desire"
    assert desire_unknown_proposition["state"] == "unknown"
    assert desire_unknown_proposition["certainty"] == "low"
    assert desire_unknown_proposition["concept"] is None

    desire_connection = await service.analyze(
        _preset_request("extended_current_desire_connection")
    )
    desire_connection_proposition = desire_connection["semantic_utterance_plan"][
        "propositions"
    ][0]
    assert desire_connection_proposition["predicate"] == "current_desire"
    assert desire_connection_proposition["state"] == "present"
    assert desire_connection_proposition["certainty"] == "medium"
    assert desire_connection_proposition["concept"] == "connection"
    assert desire_connection_proposition["evidence_refs"] == [
        "response_content_plan.primary_desire"
    ]


def test_extended_presets_are_semantic_lab_only_inputs_not_expected_answers() -> None:
    expected_keys = {
        "extended_joy_high",
        "extended_sadness_unknown_low",
        "extended_sadness_explicit_unknown",
        "extended_current_feeling_mixed",
        "extended_current_desire_unknown",
        "extended_current_desire_connection",
    }

    assert expected_keys.issubset(base._PRESETS)
    for key in expected_keys:
        preset = base._PRESETS[key]
        data = preset["data"]
        assert isinstance(data, dict)
        assert "expected_speech" not in data
        assert data["include_prompts"] is False
