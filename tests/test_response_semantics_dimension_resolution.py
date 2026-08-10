from __future__ import annotations

import json
from dataclasses import replace

from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.runtime.response_semantics_planner import ResponseSemanticsPlanner


def _context(target_id: str, emotion: dict[str, object]) -> ResponseContext:
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
    return ResponseContext(
        user_input="今どう？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="質問へ直接答える",
        speech_act="question",
        emotion=emotion,
        drive={},
        relationship={},
        memory={},
        constraints={"_internal_directive": envelope},
    )


def _primary(context: ResponseContext):
    plan = ResponseSemanticsPlanner().plan(context)
    assert len(plan.propositions) == 1
    return plan, plan.propositions[0]


def test_reactive_joy_wins_even_when_baseline_is_inserted_first() -> None:
    plan, proposition = _primary(
        _context(
            "joy",
            {
                "baseline": {"joy": 0.9},
                "current": {"reactive": {"joy": 0.0}},
            },
        )
    )

    assert proposition.state == "absent"
    assert proposition.evidence_refs == ("emotion.current.reactive.joy",)
    assert "0.9" not in json.dumps(plan.as_context(), ensure_ascii=False)


def test_reactive_joy_resolution_does_not_depend_on_mapping_insertion_order() -> None:
    first_plan, first = _primary(
        _context(
            "joy",
            {
                "baseline": {"joy": 0.9},
                "current": {"reactive": {"joy": 0.0}},
            },
        )
    )
    second_plan, second = _primary(
        _context(
            "joy",
            {
                "current": {"reactive": {"joy": 0.0}},
                "baseline": {"joy": 0.9},
            },
        )
    )

    assert first.state == second.state == "absent"
    assert first.evidence_refs == second.evidence_refs == (
        "emotion.current.reactive.joy",
    )
    assert first_plan.propositions == second_plan.propositions


def test_direct_reactive_mapping_wins_over_other_nested_exact_match() -> None:
    _, proposition = _primary(
        _context(
            "fear",
            {
                "legacy": {"fear": 0.9},
                "reactive": {"fear": 0.2},
            },
        )
    )

    assert proposition.state == "low"
    assert proposition.evidence_refs == ("emotion.reactive.fear",)


def test_current_prefix_still_uses_reactive_domain_owner() -> None:
    _, proposition = _primary(
        _context(
            "current_anger",
            {
                "current_anger": 0.9,
                "current": {"reactive": {"anger": 0.0}},
            },
        )
    )

    assert proposition.predicate == "current_anger"
    assert proposition.state == "absent"
    assert proposition.evidence_refs == ("emotion.current.reactive.anger",)


def test_exact_key_wins_over_suffix_compatibility_without_reactive_path() -> None:
    _, proposition = _primary(
        _context(
            "energy",
            {
                "legacy_energy": 0.9,
                "energy": 0.2,
            },
        )
    )

    assert proposition.state == "low"
    assert proposition.evidence_refs == ("emotion.energy",)


def test_same_rank_exact_matches_use_deterministic_path_tie_break() -> None:
    _, first = _primary(
        _context(
            "focus",
            {
                "zeta": {"focus": 0.9},
                "alpha": {"focus": 0.2},
            },
        )
    )
    _, second = _primary(
        _context(
            "focus",
            {
                "alpha": {"focus": 0.2},
                "zeta": {"focus": 0.9},
            },
        )
    )

    assert first.state == second.state == "low"
    assert first.evidence_refs == second.evidence_refs == ("emotion.alpha.focus",)
