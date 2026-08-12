from __future__ import annotations

from typing import Mapping

import pytest

from app.application.structured_character_service import (
    CharacterStructuredOutputError,
    StructuredCharacterService,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.semantic_utterance_v2 import (
    SemanticPropositionV2,
    SemanticUtterancePlanV2,
    SemanticValue,
)
from app.ports.structured_output import StructuredOutputContract


class FakeStructuredCharacterModel:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = payload
        self.activity: Activity | None = None
        self.contract: StructuredOutputContract | None = None

    async def generate_character_utterance(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        self.activity = activity
        self.contract = contract
        return self.payload


def _source() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザーへ返答する",
    )


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="好奇心がある",
        speaking_style="自然体",
        streaming_style="落ち着いた雑談",
    )


def _plan() -> SemanticUtterancePlanV2:
    return SemanticUtterancePlanV2(
        speech_act="answer",
        propositions=(
            SemanticPropositionV2(
                proposition_id="p1",
                kind="internal_state",
                predicate="joy",
                value=SemanticValue(
                    status="known",
                    polarity="present",
                    degree="high",
                    certainty="medium",
                ),
                realization_policy="required",
            ),
        ),
    )


@pytest.mark.asyncio
async def test_service_generates_typed_utterance_through_structured_contract() -> None:
    model = FakeStructuredCharacterModel(
        {
            "speech": "うれしいよ。",
            "linguistic_performance": {
                "phrasing": ["うれしいよ"],
                "emphasis": ["うれしい"],
                "delivery_tags": ["gentle"],
            },
            "realizations": [
                {
                    "proposition_id": "p1",
                    "evidence_spans": ["うれしい"],
                }
            ],
        }
    )
    service = StructuredCharacterService(
        model,
        character_profile=_profile(),
    )

    utterance = await service.generate(
        _source(),
        _plan(),
        user_wording_hint="今どんな気分？",
    )

    assert utterance.speech == "うれしいよ。"
    assert model.contract is not None
    assert model.contract.name == "character_utterance_v2"
    assert model.contract.strict is True
    assert model.activity is not None
    assert model.activity.context["llm_role"] == "character_language_realizer_v2"
    prompt = model.activity.context["plugin_prompt_override"]
    assert isinstance(prompt, str)
    assert "Role: Character Language Realizer" in prompt


@pytest.mark.asyncio
async def test_service_rejects_schema_shaped_but_unknown_alignment() -> None:
    model = FakeStructuredCharacterModel(
        {
            "speech": "うれしいよ。",
            "linguistic_performance": {
                "phrasing": [],
                "emphasis": [],
                "delivery_tags": [],
            },
            "realizations": [
                {
                    "proposition_id": "not-planned",
                    "evidence_spans": ["うれしい"],
                }
            ],
        }
    )
    service = StructuredCharacterService(model, character_profile=_profile())

    with pytest.raises(CharacterStructuredOutputError, match="Planに存在しない"):
        await service.generate(_source(), _plan())


@pytest.mark.asyncio
async def test_service_rejects_missing_required_alignment() -> None:
    model = FakeStructuredCharacterModel(
        {
            "speech": "短く返すね。",
            "linguistic_performance": {
                "phrasing": [],
                "emphasis": [],
                "delivery_tags": [],
            },
            "realizations": [],
        }
    )
    service = StructuredCharacterService(model, character_profile=_profile())

    with pytest.raises(CharacterStructuredOutputError, match="required proposition"):
        await service.generate(_source(), _plan())
