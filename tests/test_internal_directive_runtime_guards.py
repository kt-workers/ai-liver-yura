from __future__ import annotations

import json

import pytest

from app.adapters.prompt import CharacterPromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.ports.llm_roles import ResponseGeneratorRoleAdapter
from app.runtime.response_claim_validator import DeterministicFactValidator


class StubResponseGenerator:
    def __init__(self, response: str) -> None:
        self.response = response

    async def generate_response(self, activity: Activity) -> str:
        del activity
        return self.response


def directive_envelope(
    *,
    speech_act: str = "statement",
    phase: str = "continue",
    mode: str = "listen",
    question_budget: int = 0,
    new_direction_budget: int = 0,
    forbidden_claims: list[str] | None = None,
    existence_boundaries: list[str] | None = None,
) -> dict[str, object]:
    return {
        "structured_input_meaning": {
            "input_speech_act": speech_act,
            "primary_intent": "conversation",
            "expected_response": "acknowledgement",
            "target": None,
            "conversation_phase_signal": phase,
        },
        "internal_directive": {
            "response_mode": mode,
            "response_goal": "validated response",
            "initiative_level": 0.9,
            "question_budget": question_budget,
            "new_direction_budget": new_direction_budget,
            "self_disclosure_level": 0.0,
            "content_requirements": [],
            "forbidden_claims": forbidden_claims or [],
        },
        "validation_notes": [],
        "character_profile": {"name": "ゆら"},
        "existence_boundaries": existence_boundaries or [],
    }


def response_context(
    envelope: dict[str, object],
    *,
    memory: dict[str, object] | None = None,
    drive: dict[str, float] | None = None,
) -> ResponseContext:
    return ResponseContext(
        user_input="あいうえお",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="会話を継続する",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="自然に応答する",
        speech_act="statement",
        conversation_phase="active",
        initiative_level=0.9,
        constraints={"_internal_directive": envelope},
        memory=memory or {},
        drive=drive or {},
    )


@pytest.mark.asyncio
async def test_empty_closing_character_response_becomes_brief_farewell() -> None:
    adapter = ResponseGeneratorRoleAdapter(StubResponseGenerator("{}"))
    activity = Activity(
        ActivityType.CONVERSATION_WITH_USER,
        "終了意図へ短く応答する",
        context={
            "response_context": {
                "conversation_phase": "winding_down",
            }
        },
    )

    payload = json.loads(await adapter.generate_character_response(activity))

    assert payload["speech"] == "おやすみ。またね。"
    assert payload["claims"][0]["claim_type"] == "conversation_only"


def test_validated_listen_directive_caps_legacy_conversation_policy() -> None:
    envelope = directive_envelope(mode="listen")
    context = response_context(
        envelope,
        memory={
            "response_content_plan": {
                "primary_desire": "curiosity",
                "conversation_strategies": [
                    "ask_for_detail",
                    "explore_related_topic",
                ],
                "question_budget": 1,
                "new_direction_budget": 1,
                "observation_only": True,
                "reasons": ["legacy_curiosity_plan"],
            }
        },
        drive={
            "curiosity": 1.0,
            "engagement": 1.0,
            "energy": 1.0,
        },
    )

    prompt = CharacterPromptBuilder().build(
        context,
        character_profile=None,
        correction=None,
    )
    decision_line = next(
        line
        for line in prompt.splitlines()
        if line.startswith("Conversation Response Decision: ")
    )
    plan_line = next(
        line
        for line in prompt.splitlines()
        if line.startswith("Response Content Plan: ")
    )
    decision = json.loads(
        decision_line.removeprefix("Conversation Response Decision: ")
    )
    content_plan = json.loads(plan_line.removeprefix("Response Content Plan: "))

    assert decision["mode"] == "listen"
    assert content_plan["question_budget"] == 0
    assert content_plan["new_direction_budget"] == 0
    assert content_plan["conversation_strategies"] == ["acknowledge_other"]
    assert "validated_internal_directive_projected" in content_plan["reasons"]


def test_question_over_budget_is_rejected_before_validator_llm() -> None:
    context = response_context(directive_envelope(question_budget=0))
    response = CharacterResponse(
        speech="最近はどんなゲームにハマってる？",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
    )

    result = DeterministicFactValidator().validate(context, response, ())

    assert result.accepted is False
    assert result.reason == "response_exceeds_internal_directive_question_budget"


def test_explicit_new_direction_over_budget_is_rejected() -> None:
    context = response_context(directive_envelope(new_direction_budget=0))
    response = CharacterResponse(
        speech="ところで、最近のゲームはどう？",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
    )

    result = DeterministicFactValidator().validate(context, response, ())

    assert result.accepted is False
    assert "response_exceeds_internal_directive_new_direction_budget" in (
        result.claim_differences
    )


def test_closing_response_cannot_reopen_conversation() -> None:
    context = response_context(
        directive_envelope(
            speech_act="closing",
            phase="winding_down",
            mode="react",
        )
    )
    response = CharacterResponse(
        speech="おやすみ。また明日は何を話そうか？",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
    )

    result = DeterministicFactValidator().validate(context, response, ())

    assert result.accepted is False
    assert "closing_response_reopens_conversation" in result.claim_differences


def test_unsupported_embodied_experience_is_rejected() -> None:
    context = response_context(
        directive_envelope(
            forbidden_claims=["現実空間での実体験を根拠なく創作しない"],
            existence_boundaries=[
                "物理的な身体を持たない",
                "実体験は根拠がある場合だけ語る",
            ],
        )
    )
    response = CharacterResponse(
        speech="水族館で実際にクラゲを間近で見たよ。",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
    )

    result = DeterministicFactValidator().validate(context, response, ())

    assert result.accepted is False
    assert "response_violates_existence_boundary" in result.claim_differences
