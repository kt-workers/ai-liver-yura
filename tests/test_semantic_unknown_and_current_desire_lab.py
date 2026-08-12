from __future__ import annotations

import pytest

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.adapters.prompt.character_realization_validator_prompt_builder import (
    CharacterRealizationValidatorPromptBuilder,
)
from app.domain.character import CharacterProfile
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.domain.character_utterance import LinguisticPerformance
from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticTarget,
    SemanticUtterancePlan,
)
from cloud_validation import character_response_lab as base
from cloud_validation.character_semantic_response_lab import (
    CharacterSemanticResponseLabService,
)


def _unknown_context() -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "current_desire"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_desire",
                state="unknown",
                certainty="low",
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
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
        memory={
            "semantic_utterance_plan": plan.as_context(),
            "semantic_validation": {
                "accepted": True,
                "reason": "semantic_plan_consistent",
                "differences": [],
            },
        },
    )


def test_unknown_state_contract_does_not_allow_guessed_presence() -> None:
    context = _unknown_context()
    profile = CharacterProfile(
        name="ゆら",
        personality="穏やか",
        speaking_style="自然な日本語",
        streaming_style="会話相手へ自然に反応する",
    )
    character_prompt = CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=profile,
        correction=None,
    )
    response = CharacterResponse(
        speech="うん、少しあるかも。",
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(
            phrasing=("うん", "少しあるかも"),
            delivery_tags=("gentle",),
        ),
        semantic_realizations=("proposition:0:current_desire",),
    )
    validator_builder = CharacterRealizationValidatorPromptBuilder()
    plan = SemanticUtterancePlan.from_context(context.memory["semantic_utterance_plan"])
    assert plan is not None
    observer_prompt = validator_builder.build_observation(context, response, plan)
    validator_prompt = validator_builder.build(context, response)

    assert '"state": "unknown"' in character_prompt
    assert "特定polarityを推測しない" in character_prompt
    assert "certaintyは指定されたstateへの確からしさ" in character_prompt
    assert "別のstateや強度を推測してよい" in character_prompt

    # Observerにはexpected unknown/lowを渡さず、speechが実際にcommitしたstate/certaintyだけを観測させる。
    assert '"state": "unknown"' not in observer_prompt
    assert '"certainty": "low"' not in observer_prompt
    assert "期待state、期待certainty、期待conceptは与えられていない" in observer_prompt
    assert "特定polarityへcommitしたspeechをunknownにしない" in observer_prompt

    # state/polarity/intensity/certaintyはObserver後のtyped比較がauthorityであり、後段では再判定しない。
    assert "state/polarity/intensity/certaintyはこの工程で判定しない" in validator_prompt
    assert "speechから再抽出せず" in validator_prompt


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
async def test_current_desire_preset_uses_production_response_content_plan_contract() -> None:
    preset = base._PRESETS["current_desire"]
    data = preset["data"]
    assert isinstance(data, dict)
    memory = data["memory"]
    assert isinstance(memory, dict)
    response_content_plan = memory["response_content_plan"]
    assert isinstance(response_content_plan, dict)
    assert response_content_plan["primary_desire"] == "curiosity"
    assert response_content_plan["observation_only"] is True

    request = base.CharacterResponseLabRequest(**data)
    result = await CharacterSemanticResponseLabService(_settings()).analyze(request)

    plan = result["semantic_utterance_plan"]
    assert isinstance(plan, dict)
    assert plan["target"] == {"type": "internal_state", "id": "current_desire"}
    propositions = plan["propositions"]
    assert isinstance(propositions, list)
    assert propositions[0]["predicate"] == "current_desire"
    assert propositions[0]["state"] == "present"
    assert propositions[0]["certainty"] == "medium"
    assert propositions[0]["concept"] == "curiosity"
    assert propositions[0]["evidence_refs"] == [
        "response_content_plan.primary_desire"
    ]
    semantic_validation = result["semantic_validation"]
    assert isinstance(semantic_validation, dict)
    assert semantic_validation["accepted"] is True
