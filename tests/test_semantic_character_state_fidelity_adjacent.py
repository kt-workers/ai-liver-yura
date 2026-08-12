from __future__ import annotations

import json

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.character_response import ActivityExecutionResult, ActivityExecutionStatus
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.internal_state_response_context import InternalStateAwareResponseContextBuilder


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やかで好奇心を持つ",
        speaking_style="やわらかく自然な話し方",
        streaming_style="会話相手へ自然に反応する",
    )


def _build_context(
    *,
    target_id: str,
    user_text: str,
    emotion: dict[str, object],
):
    envelope = {
        "structured_input_meaning": {
            "input_speech_act": "question",
            "primary_intent": "ask_internal_state",
            "expected_response": "direct_answer",
            "target": {"type": "internal_state", "id": target_id},
        },
        "internal_directive": {
            "response_mode": "answer",
            "response_goal": "現在の内部状態へ自然に直接答える",
            "question_budget": 0,
            "new_direction_budget": 0,
            "self_disclosure_level": 0.35,
            "content_requirements": [],
            "forbidden_claims": [],
        },
    }
    result = ActivityExecutionResult(
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        constraints={"_internal_directive": envelope},
    )
    payload = {
        "text": user_text,
        "activity_execution_result": result,
        "emotion": emotion,
    }
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ直接答える",
        context={
            "activity_execution_result": result,
            "event_payload": payload,
        },
    )
    return InternalStateAwareResponseContextBuilder().build(activity)


def _plan(context) -> SemanticUtterancePlan:
    plan = SemanticUtterancePlan.from_context(
        context.memory.get("semantic_utterance_plan")
    )
    assert plan is not None
    return plan


def _prompt(context) -> str:
    return CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=_profile(),
        correction=None,
    )


def _character_plan_from_prompt(prompt: str) -> dict[str, object]:
    lines = prompt.splitlines()
    marker = "# Semantic Utterance Plan for Character"
    index = lines.index(marker)
    value = json.loads(lines[index + 1])
    assert isinstance(value, dict)
    return value


def _primary_contract_from_prompt(prompt: str) -> dict[str, object]:
    lines = prompt.splitlines()
    marker = "# Required Facet Realization Contract"
    index = lines.index(marker)
    value = json.loads(lines[index + 1])
    assert isinstance(value, dict)
    return value


def test_high_joy_from_production_planner_keeps_explicit_intensity_contract() -> None:
    context = _build_context(
        target_id="joy",
        user_text="楽しい？",
        emotion={"current": {"reactive": {"joy": 0.78}}},
    )
    plan = _plan(context)
    prompt = _prompt(context)
    character_plan = _character_plan_from_prompt(prompt)
    primary_contract = _primary_contract_from_prompt(prompt)

    primary = plan.propositions[0]
    assert primary.predicate == "joy"
    assert primary.state == "high"
    assert primary.certainty == "high"
    assert primary.evidence_refs == ("emotion.current.reactive.joy",)

    character_primary = character_plan["propositions"][0]
    assert character_primary["state"] == "high"
    assert character_primary["state_semantics"] == "explicit_intensity_state"
    assert character_primary["intensity_fidelity"] == "must_preserve_intensity_if_realized"
    assert primary_contract["state_fidelity"] == "preserve_exact_semantic_state"
    assert primary_contract["intensity_fidelity"] == "must_preserve_intensity_if_realized"

    assert "emotion.current.reactive.joy" not in prompt
    assert "evidence_refs" not in prompt
    assert "0.78" not in prompt


def test_missing_sadness_from_production_planner_keeps_unknown_without_polarity() -> None:
    context = _build_context(
        target_id="sadness",
        user_text="悲しい？",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.22,
                    "amusement": 0.08,
                    "calm": 0.55,
                    "anger": 0.0,
                }
            }
        },
    )
    plan = _plan(context)
    prompt = _prompt(context)
    character_plan = _character_plan_from_prompt(prompt)
    primary_contract = _primary_contract_from_prompt(prompt)

    primary = plan.propositions[0]
    assert primary.predicate == "sadness"
    assert primary.state == "unknown"
    assert primary.certainty == "low"
    assert primary.evidence_refs == ()

    character_primary = character_plan["propositions"][0]
    assert character_primary["state"] == "unknown"
    assert character_primary["certainty"] == "low"
    assert character_primary["state_semantics"] == "unknown_without_polarity_guess"
    assert character_primary["polarity_commitment"] == "forbidden"
    assert primary_contract["polarity_commitment"] == "forbidden"
    assert "肯定・否定markerでpolarityを確定しない" in prompt


def test_mixed_current_feeling_supporting_states_keep_facet_complete_policy() -> None:
    context = _build_context(
        target_id="current_feeling",
        user_text="今どんな気分？",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.78,
                    "anger": 0.48,
                    "calm": 0.22,
                    "amusement": 0.02,
                }
            }
        },
    )
    plan = _plan(context)
    prompt = _prompt(context)
    character_plan = _character_plan_from_prompt(prompt)

    expected_states = {
        "current_feeling": "overview",
        "joy": "high",
        "anger": "moderate",
        "calm": "low",
        "amusement": "absent",
    }
    assert {item.predicate: item.state for item in plan.propositions} == expected_states

    character_props = {
        item["predicate"]: item for item in character_plan["propositions"]
    }
    assert character_props["current_feeling"]["realization_policy"] == "required"
    for predicate in ("joy", "anger", "calm", "amusement"):
        proposition = character_props[predicate]
        assert proposition["realization_policy"] == "optional_but_facet_complete_if_realized"
        assert proposition["if_realized_required_facets"] == [
            "predicate",
            "state",
            "certainty",
        ]

    for predicate in ("joy", "anger", "calm"):
        assert (
            character_props[predicate]["intensity_fidelity"]
            == "must_preserve_intensity_if_realized"
        )
    assert character_props["amusement"]["intensity_fidelity"] == "not_applicable"

    assert "supporting propositionは省略可能" in prompt
    assert "emotion.current.reactive.joy" not in prompt
    assert "emotion.current.reactive.anger" not in prompt
    assert "0.78" not in prompt
    assert "0.48" not in prompt
    assert "0.22" not in prompt
