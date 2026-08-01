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
    MoralActivityCandidateEvaluator,
    MoralProfile,
    MoralState,
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


def _moral_context(
    profile: MoralProfile,
    state: MoralState,
) -> dict[str, object]:
    return {
        "profile": profile.as_dict(),
        "state": state.as_dict(),
        "composite": profile.compose(state).as_dict(),
        "observation_only": True,
    }


def _planning_input(prompt: str) -> dict[str, object]:
    lines = prompt.splitlines()
    marker_index = lines.index("# 判断入力")
    payload = json.loads(lines[marker_index + 1])
    assert isinstance(payload, dict)
    return payload


def test_social_candidate_fit_reflects_compassion_and_empathy() -> None:
    evaluator = MoralActivityCandidateEvaluator()
    profile = MoralProfile(
        compassion=1.0,
        honesty=0.8,
        altruism=0.9,
        dominance=0.0,
        competitiveness=0.0,
    )
    state = MoralState(
        restraint=0.8,
        empathy_activation=1.0,
        selfish_impulse=0.0,
        aggressive_impulse=0.0,
        guilt=0.2,
    )

    social = evaluator.evaluate_activity(
        "conversation_with_user",
        profile=profile,
        state=state,
    )
    assertive = evaluator.evaluate_activity(
        "autonomous_talk",
        profile=profile,
        state=state,
    )

    assert social.profiled is True
    assert social.observation_only is True
    assert social.moral_fit > assertive.moral_fit


def test_unknown_activity_uses_neutral_fit_without_becoming_prohibited() -> None:
    fit = MoralActivityCandidateEvaluator().evaluate_activity(
        "future_activity",
        profile=MoralProfile(),
        state=MoralState(),
    )

    assert fit.moral_fit == pytest.approx(0.5)
    assert fit.profiled is False
    assert fit.observation_only is True
    assert fit.reason == "unprofiled_activity_neutral"


def test_prompt_projects_moral_fit_without_changing_motivation_order() -> None:
    profile = MoralProfile(compassion=1.0, dominance=0.0)
    state = MoralState(
        restraint=0.8,
        empathy_activation=1.0,
        selfish_impulse=0.0,
        aggressive_impulse=0.0,
        guilt=0.1,
    )
    context = BehaviorPlanningContext(
        user_text="次は何をしようか",
        source_event_id="event-moral-1",
        available_capabilities=frozenset(),
        activity_definitions=(
            _definition("conversation_with_user"),
            _definition("plugin_activity"),
        ),
        motivation={"recommended_activity_types": ["plugin_activity"]},
        moral=_moral_context(profile, state),
    )

    prompt = SituationEvaluatorPromptBuilder().build(context)
    planning_input = _planning_input(prompt)
    available = planning_input["available_activities"]
    moral_fits = planning_input["activity_candidate_moral_fits"]

    assert isinstance(available, list)
    assert isinstance(moral_fits, list)
    assert [item["activity_type"] for item in available] == [
        "plugin_activity",
        "conversation_with_user",
    ]
    assert all(item["observation_only"] is True for item in moral_fits)
    fit_by_type = {item["activity_type"]: item for item in moral_fits}
    assert (
        fit_by_type["conversation_with_user"]["moral_fit"]
        > fit_by_type["plugin_activity"]["moral_fit"]
    )
    assert "候補の選択、並べ替え、禁止、抑制へ使用しない" in prompt
