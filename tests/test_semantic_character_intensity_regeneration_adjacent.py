from __future__ import annotations

import json

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.character_response import ActivityExecutionResult, ActivityExecutionStatus
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.character_language_realizer_service import CharacterLanguageRealizerService
from app.runtime.internal_state_response_context import InternalStateAwareResponseContextBuilder


def _production_high_joy_context():
    envelope = {
        "structured_input_meaning": {
            "input_speech_act": "question",
            "primary_intent": "ask_internal_state",
            "expected_response": "direct_answer",
            "target": {"type": "internal_state", "id": "joy"},
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
        "text": "楽しい？",
        "activity_execution_result": result,
        "emotion": {"current": {"reactive": {"joy": 0.78}}},
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


def _section_json(prompt: str, marker: str) -> dict[str, object]:
    lines = prompt.splitlines()
    index = lines.index(marker)
    value = json.loads(lines[index + 1])
    assert isinstance(value, dict)
    return value


def test_production_high_joy_regeneration_keeps_exact_intensity_contract() -> None:
    context = _production_high_joy_context()
    plan = SemanticUtterancePlan.from_context(
        context.memory.get("semantic_utterance_plan")
    )
    assert plan is not None
    primary = plan.propositions[0]
    assert primary.predicate == "joy"
    assert primary.state == "high"
    assert primary.certainty == "high"

    e1_correction = json.dumps(
        {
            "reason": "state_intensity_overstated",
            "claim_differences": [
                "'かなり' が plan の high を超える強い程度表現として追加され、state fidelity が exact ではありません"
            ],
        },
        ensure_ascii=False,
    )
    normalized = CharacterLanguageRealizerService._normalize_state_fidelity_correction(
        e1_correction
    )
    assert normalized is not None

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=CharacterProfile(
            name="ゆら",
            personality="穏やかで好奇心を持つ",
            speaking_style="やわらかく自然な話し方",
            streaming_style="会話相手へ自然に反応する",
        ),
        correction=normalized,
    )
    character_plan = _section_json(
        prompt, "# Semantic Utterance Plan for Character"
    )
    primary_contract = _section_json(
        prompt, "# Required Facet Realization Contract"
    )

    character_primary = character_plan["propositions"][0]
    assert character_primary["predicate"] == "joy"
    assert character_primary["state"] == "high"
    assert character_primary["certainty"] == "high"
    assert (
        character_primary["intensity_fidelity"]
        == "must_preserve_intensity_if_realized"
    )
    assert primary_contract["state"] == "high"
    assert primary_contract["state_fidelity"] == "preserve_exact_semantic_state"
    assert primary_contract["intensity_fidelity"] == "must_preserve_intensity_if_realized"
    assert '"restore_state_fidelity"' in prompt
    assert "Planのstateをpresenceだけへ弱めず" in prompt
    assert "存在だけへ弱めず強度差を意味的に保持" in prompt

    assert "emotion.current.reactive.joy" not in prompt
    assert "evidence_refs" not in prompt
    assert "0.78" not in prompt
