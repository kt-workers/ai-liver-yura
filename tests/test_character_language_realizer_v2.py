from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.adapters.prompt.character_language_realizer_v2_prompt_builder import (
    CharacterLanguageRealizerV2PromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticTarget,
    SemanticUtterancePlan,
)
from app.ports.structured_output import StructuredOutputContract, StructuredOutputGenerationError
from app.runtime.character_language_realizer_v2 import CharacterLanguageRealizerV2


class _StructuredCharacterModel:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[Activity, StructuredOutputContract]] = []

    async def generate_structured_character_response(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        self.calls.append((activity, contract))
        return self.payload


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やかで好奇心を持つ",
        speaking_style="自然な日本語",
        streaming_style="自然な会話",
    )


def _plan() -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "current_desire"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_desire",
                state="present",
                certainty="medium",
                concept="curiosity",
                evidence_refs=("response_content_plan.primary_desire",),
            ),
        ),
        forbidden_additions=("unsupported_new_self_state",),
        response_length="short",
        self_disclosure="brief",
    )


def _context() -> ResponseContext:
    return ResponseContext(
        user_input="何かしたい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の欲求へ直接答える",
        speech_act="question",
        emotion={"current": {"reactive": {"joy": 0.9}}},
        drive={"curiosity": 0.99},
        memory={"semantic_utterance_plan": _plan().as_context()},
    )


def _source() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="reply",
        context={"event_id": "event-v2"},
    )


@pytest.mark.asyncio
async def test_v2_realizer_uses_structured_output_and_alignment_spans() -> None:
    proposition_id = _plan().propositions[0].proposition_id
    model = _StructuredCharacterModel(
        {
            "speech": "たぶん、好奇心から何かしたい感じはあるよ。",
            "linguistic_performance": {
                "phrasing": ["たぶん", "好奇心から何かしたい感じはあるよ"],
                "emphasis": ["好奇心"],
                "delivery_tags": ["gentle"],
            },
            "realizations": [
                {
                    "proposition_id": proposition_id,
                    "evidence_spans": ["好奇心から何かしたい感じはある"],
                }
            ],
        }
    )
    service = CharacterLanguageRealizerV2(
        model,
        CharacterLanguageRealizerV2PromptBuilder(),
        character_profile=_profile(),
    )

    utterance = await service.generate_utterance(_source(), _context())

    assert utterance.semantic_realizations == (proposition_id,)
    assert utterance.realizations[0].evidence_spans == (
        "好奇心から何かしたい感じはある",
    )
    activity, contract = model.calls[0]
    assert activity.context["llm_role"] == "character_language_realizer_v2"
    assert contract.name == "character_utterance_v2"
    assert contract.strict is True


def test_v2_prompt_contains_normalized_facets_but_not_raw_state_evidence_or_json_schema_prose() -> None:
    prompt = CharacterLanguageRealizerV2PromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=None,
    )

    assert '"status":"known"' in prompt
    assert '"polarity":"present"' in prompt
    assert '"degree":null' in prompt
    assert '"certainty":"medium"' in prompt
    assert '"concept":"curiosity"' in prompt
    assert "response_content_plan.primary_desire" not in prompt
    assert "0.99" not in prompt
    assert "JSONのみ返す" not in prompt
    assert "Required Facet Realization Contract" not in prompt


@pytest.mark.asyncio
async def test_v2_realizer_rejects_unplanned_alignment_id() -> None:
    model = _StructuredCharacterModel(
        {
            "speech": "たぶん何かしたい感じはあるよ。",
            "linguistic_performance": {
                "phrasing": [],
                "emphasis": [],
                "delivery_tags": [],
            },
            "realizations": [
                {
                    "proposition_id": "unplanned",
                    "evidence_spans": ["何かしたい感じはある"],
                }
            ],
        }
    )
    service = CharacterLanguageRealizerV2(
        model,
        CharacterLanguageRealizerV2PromptBuilder(),
        character_profile=_profile(),
    )

    with pytest.raises(StructuredOutputGenerationError):
        await service.generate_utterance(_source(), _context())


@pytest.mark.asyncio
async def test_v2_realizer_requires_alignment_for_required_proposition() -> None:
    model = _StructuredCharacterModel(
        {
            "speech": "たぶん何かしたい感じはあるよ。",
            "linguistic_performance": {
                "phrasing": [],
                "emphasis": [],
                "delivery_tags": [],
            },
            "realizations": [],
        }
    )
    service = CharacterLanguageRealizerV2(
        model,
        CharacterLanguageRealizerV2PromptBuilder(),
        character_profile=_profile(),
    )

    with pytest.raises(StructuredOutputGenerationError):
        await service.generate_utterance(_source(), _context())
