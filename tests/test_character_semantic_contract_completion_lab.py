from __future__ import annotations

import pytest

from cloud_validation import character_response_lab as base
from cloud_validation.character_semantic_contract_completion_lab import (
    service,
)


def _preset_request(key: str) -> base.CharacterResponseLabRequest:
    preset = base._PRESETS[key]
    data = preset["data"]
    assert isinstance(data, dict)
    return base.CharacterResponseLabRequest(**data)


@pytest.mark.asyncio
async def test_drive_contract_completion_presets_use_drive_as_semantic_source() -> None:
    curiosity = await service.analyze(
        _preset_request("extended_drive_curiosity_high")
    )
    curiosity_proposition = curiosity["semantic_utterance_plan"]["propositions"][0]
    assert curiosity_proposition["predicate"] == "curiosity"
    assert curiosity_proposition["state"] == "high"
    assert curiosity_proposition["certainty"] == "high"
    assert curiosity_proposition["concept"] is None
    assert curiosity_proposition["evidence_refs"] == ["drive.curiosity"]

    energy = await service.analyze(_preset_request("extended_drive_energy_low"))
    energy_proposition = energy["semantic_utterance_plan"]["propositions"][0]
    assert energy_proposition["predicate"] == "energy"
    assert energy_proposition["state"] == "low"
    assert energy_proposition["certainty"] == "high"
    assert energy_proposition["concept"] is None
    assert energy_proposition["evidence_refs"] == ["drive.energy"]


@pytest.mark.asyncio
async def test_drive_contract_completion_presets_keep_raw_drive_out_of_model_boundary() -> None:
    result = await service.analyze(
        _preset_request("extended_drive_curiosity_high")
    )

    character_boundary = result["character_model_boundary"]
    observer_boundary = result["observer_model_boundary"]
    validator_boundary = result["validator_model_boundary"]
    assert isinstance(character_boundary, dict)
    assert isinstance(observer_boundary, dict)
    assert isinstance(validator_boundary, dict)
    assert "drive" not in character_boundary["context_keys"]
    assert "drive" not in observer_boundary["context_keys"]
    assert "drive" not in validator_boundary["context_keys"]
    assert character_boundary["semantic_boundary"] is True
    assert observer_boundary["semantic_boundary"] is True
    assert validator_boundary["semantic_boundary"] is True


def test_contract_completion_presets_are_live_inputs_not_expected_answers() -> None:
    expected = {
        "extended_drive_curiosity_high",
        "extended_drive_energy_low",
    }

    assert expected.issubset(base._PRESETS)
    for key in expected:
        preset = base._PRESETS[key]
        data = preset["data"]
        assert isinstance(data, dict)
        assert "expected_speech" not in data
        assert data["include_prompts"] is False
