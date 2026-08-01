from __future__ import annotations

import json

import pytest

from app.adapters.prompt import SituationEvaluatorPromptBuilder
from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    BehaviorPlanningContext,
)
from app.domain.morals import (
    ActivityCandidateSemanticEquivalenceEvidence,
    MoralActivityCandidateFit,
    MoralActivityCandidatePreferenceShadowEvaluator,
    MoralProfile,
    MoralState,
    SemanticEquivalenceDimension,
    SemanticEquivalenceStatus,
)


def _definition(activity_type: str) -> ActivityDefinition:
    return ActivityDefinition(
        activity_type=activity_type,
        display_name=activity_type,
        required_capability=None,
        provider_plugin_id="runtime",
        description=f"{activity_type}を行う",
        supported_operations=(ActivityOperation.START,),
        constraints_schema={"type": "object", "additionalProperties": False},
    )


def _fit(activity_type: str, value: float) -> MoralActivityCandidateFit:
    return MoralActivityCandidateFit(
        activity_type=activity_type,
        moral_fit=value,
        profiled=True,
    )


def _preference(
    activity_type: str,
    *,
    motivation_score: float,
    pinned: bool = False,
) -> dict[str, object]:
    return {
        "activity_type": activity_type,
        "motivation_score": motivation_score,
        "pinned": pinned,
    }


def _moral_context(
    *,
    aggressive_impulse: float = 0.2,
    selfish_impulse: float = 0.2,
) -> dict[str, object]:
    profile = MoralProfile()
    state = MoralState(
        aggressive_impulse=aggressive_impulse,
        selfish_impulse=selfish_impulse,
    )
    return {
        "profile": profile.as_dict(),
        "state": state.as_dict(),
        "composite": profile.compose(state).as_dict(),
        "observation_only": True,
    }


def _semantic_evidence(
    candidate_group: tuple[str, ...],
) -> ActivityCandidateSemanticEquivalenceEvidence:
    return ActivityCandidateSemanticEquivalenceEvidence(
        candidate_group=candidate_group,
        intent=SemanticEquivalenceDimension.CONFIRMED,
        operation=SemanticEquivalenceDimension.CONFIRMED,
        goal=SemanticEquivalenceDimension.CONFIRMED,
        source="situation_evaluator_shadow",
        evidence_id="semantic-shadow-1",
    )


def _planning_input(prompt: str) -> dict[str, object]:
    lines = prompt.splitlines()
    marker_index = lines.index("# 判断入力")
    payload = json.loads(lines[marker_index + 1])
    assert isinstance(payload, dict)
    return payload


def test_shadow_computes_hypothetical_order_without_activation() -> None:
    definitions = (
        _definition("autonomous_talk"),
        _definition("conversation_with_user"),
        _definition("plugin_activity"),
    )
    result = MoralActivityCandidatePreferenceShadowEvaluator().evaluate(
        definitions,
        (
            _fit("autonomous_talk", 0.60),
            _fit("conversation_with_user", 0.76),
            _fit("plugin_activity", 0.55),
        ),
        (
            _preference("autonomous_talk", motivation_score=0.0),
            _preference("conversation_with_user", motivation_score=0.0),
            _preference("plugin_activity", motivation_score=1.0),
        ),
        _moral_context(),
    )

    assert result.static_eligible is True
    assert result.semantic_equivalence_confirmed is False
    assert result.activation_permitted is False
    assert result.preferred_activity_type == "conversation_with_user"
    assert result.current_order == (
        "autonomous_talk",
        "conversation_with_user",
        "plugin_activity",
    )
    assert result.hypothetical_order == (
        "conversation_with_user",
        "autonomous_talk",
        "plugin_activity",
    )
    assert result.fit_margin == pytest.approx(0.16)
    assert (
        result.semantic_equivalence.status
        is SemanticEquivalenceStatus.UNCONFIRMED
    )
    assert "shadow_mode_only" in result.reasons
    assert "semantic_equivalence_unconfirmed" in result.reasons


def test_confirmed_semantic_equivalence_still_does_not_activate() -> None:
    candidate_group = (
        "autonomous_talk",
        "conversation_with_user",
    )
    definitions = tuple(_definition(item) for item in candidate_group)
    result = MoralActivityCandidatePreferenceShadowEvaluator().evaluate(
        definitions,
        (
            _fit("autonomous_talk", 0.60),
            _fit("conversation_with_user", 0.76),
        ),
        (
            _preference("autonomous_talk", motivation_score=0.0),
            _preference("conversation_with_user", motivation_score=0.0),
        ),
        _moral_context(),
        _semantic_evidence(candidate_group),
    )

    assert result.static_eligible is True
    assert result.semantic_equivalence_confirmed is True
    assert result.activation_permitted is False
    assert (
        result.semantic_equivalence.status
        is SemanticEquivalenceStatus.CONFIRMED
    )
    assert (
        "semantic_equivalence_confirmed_but_activation_disabled"
        in result.reasons
    )
    assert result.hypothetical_order == (
        "conversation_with_user",
        "autonomous_talk",
    )


def test_shadow_rejects_small_fit_margin() -> None:
    definitions = (
        _definition("autonomous_talk"),
        _definition("conversation_with_user"),
    )
    result = MoralActivityCandidatePreferenceShadowEvaluator().evaluate(
        definitions,
        (
            _fit("autonomous_talk", 0.60),
            _fit("conversation_with_user", 0.64),
        ),
        (
            _preference("autonomous_talk", motivation_score=0.0),
            _preference("conversation_with_user", motivation_score=0.0),
        ),
        _moral_context(),
    )

    assert result.static_eligible is False
    assert result.activation_permitted is False
    assert result.hypothetical_order == result.current_order
    assert "fit_margin_below_threshold" in result.reasons


def test_shadow_rejects_unstable_moral_state() -> None:
    definitions = (
        _definition("autonomous_talk"),
        _definition("conversation_with_user"),
    )
    result = MoralActivityCandidatePreferenceShadowEvaluator().evaluate(
        definitions,
        (
            _fit("autonomous_talk", 0.60),
            _fit("conversation_with_user", 0.76),
        ),
        (
            _preference("autonomous_talk", motivation_score=0.0),
            _preference("conversation_with_user", motivation_score=0.0),
        ),
        _moral_context(aggressive_impulse=0.80),
    )

    assert result.static_eligible is False
    assert result.hypothetical_order == result.current_order
    assert "moral_state_unstable" in result.reasons


def test_shadow_keeps_pinned_activity_outside_comparison_group() -> None:
    definitions = (
        _definition("autonomous_talk"),
        _definition("plugin_activity"),
        _definition("conversation_with_user"),
    )
    result = MoralActivityCandidatePreferenceShadowEvaluator().evaluate(
        definitions,
        (
            _fit("autonomous_talk", 0.95),
            _fit("plugin_activity", 0.60),
            _fit("conversation_with_user", 0.76),
        ),
        (
            _preference(
                "autonomous_talk",
                motivation_score=1.0,
                pinned=True,
            ),
            _preference("plugin_activity", motivation_score=0.0),
            _preference("conversation_with_user", motivation_score=0.0),
        ),
        _moral_context(),
    )

    assert result.static_eligible is True
    assert result.candidate_group == (
        "plugin_activity",
        "conversation_with_user",
    )
    assert result.current_order[0] == "autonomous_talk"
    assert result.hypothetical_order[0] == "autonomous_talk"
    assert result.hypothetical_order[1:] == (
        "conversation_with_user",
        "plugin_activity",
    )


def test_prompt_projects_shadow_without_changing_available_order() -> None:
    context = BehaviorPlanningContext(
        user_text="次は何をしようか",
        source_event_id="event-moral-shadow-1",
        available_capabilities=frozenset(),
        activity_definitions=(
            _definition("autonomous_talk"),
            _definition("conversation_with_user"),
        ),
        motivation={"recommended_activity_types": []},
        moral=_moral_context(),
    )

    prompt = SituationEvaluatorPromptBuilder().build(context)
    planning_input = _planning_input(prompt)
    available = planning_input["available_activities"]
    shadow = planning_input["moral_candidate_preference_shadow"]
    semantic_equivalence = planning_input[
        "activity_candidate_semantic_equivalence"
    ]

    assert isinstance(available, list)
    assert isinstance(shadow, dict)
    assert isinstance(semantic_equivalence, dict)
    actual_order = [item["activity_type"] for item in available]
    assert actual_order == shadow["current_order"]
    assert shadow["activation_permitted"] is False
    assert shadow["semantic_equivalence"] == semantic_equivalence
    assert semantic_equivalence["status"] == "unconfirmed"
    assert "hypothetical_order" in shadow
    assert (
        "semantic_equivalence_confirmedをActivity選択へ使用しない"
        in prompt
    )
