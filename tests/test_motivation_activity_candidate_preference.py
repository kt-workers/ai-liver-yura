from __future__ import annotations

import json

import pytest

from app.adapters.prompt import SituationEvaluatorPromptBuilder
from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    BehaviorPlanningContext,
)
from app.domain.motivation import MotivationActivityCandidateRanker
from app.runtime.situation_evaluator import SituationEvaluator
from app.shared.contracts.activity import (
    ActivityMatcherContext,
    DeterministicActivityMatch,
)


def _definition(
    activity_type: str,
    *,
    matcher: object | None = None,
) -> ActivityDefinition:
    return ActivityDefinition(
        activity_type=activity_type,
        display_name=activity_type,
        required_capability=None,
        provider_plugin_id="runtime",
        description=f"{activity_type}を行う",
        supported_operations=(ActivityOperation.START,),
        constraints_schema={
            "type": "object",
            "additionalProperties": False,
        },
        matcher=matcher,
    )


def _definitions() -> tuple[ActivityDefinition, ...]:
    return (
        _definition("conversation_with_user"),
        _definition("topic_exploration"),
        _definition("plugin_activity"),
    )


def _planning_input(prompt: str) -> dict[str, object]:
    lines = prompt.splitlines()
    marker_index = lines.index("# 判断入力")
    payload = json.loads(lines[marker_index + 1])
    assert isinstance(payload, dict)
    return payload


def test_ranker_prioritizes_only_existing_recommended_candidates() -> None:
    ranking = MotivationActivityCandidateRanker().rank(
        _definitions(),
        {
            "recommended_activity_types": [
                "plugin_activity",
                "unknown_activity",
                "topic_exploration",
            ]
        },
    )

    assert [item.activity_type for item in ranking.definitions] == [
        "plugin_activity",
        "topic_exploration",
        "conversation_with_user",
    ]
    assert [item.activity_type for item in ranking.preferences] == [
        "plugin_activity",
        "topic_exploration",
        "conversation_with_user",
    ]
    assert ranking.preferences[0].recommendation_rank == 1
    assert ranking.preferences[0].motivation_score == pytest.approx(1.0)
    assert ranking.preferences[1].recommendation_rank == 2
    assert ranking.preferences[1].motivation_score == pytest.approx(0.5)
    assert all(
        item.activity_type != "unknown_activity" for item in ranking.preferences
    )


def test_ranker_preserves_ongoing_activity_before_motivation_order() -> None:
    ranking = MotivationActivityCandidateRanker().rank(
        _definitions(),
        {
            "recommended_activity_types": [
                "plugin_activity",
                "topic_exploration",
            ]
        },
        pinned_activity_types=("conversation_with_user",),
    )

    assert [item.activity_type for item in ranking.definitions] == [
        "conversation_with_user",
        "plugin_activity",
        "topic_exploration",
    ]
    assert ranking.preferences[0].pinned is True
    assert ranking.preferences[0].reason == "ongoing_activity_preserved"


def test_prompt_projects_motivation_as_tie_breaking_candidate_preference() -> None:
    context = BehaviorPlanningContext(
        user_text="次は何をしようか",
        source_event_id="event-1",
        available_capabilities=frozenset(),
        activity_definitions=_definitions(),
        ongoing_activity_type="conversation_with_user",
        motivation={
            "primary_desire": "autonomy",
            "recommended_activity_types": [
                "plugin_activity",
                "unknown_activity",
                "topic_exploration",
            ],
            "moral_evaluation_available": False,
        },
    )

    prompt = SituationEvaluatorPromptBuilder().build(context)
    planning_input = _planning_input(prompt)
    available = planning_input["available_activities"]
    preferences = planning_input["activity_candidate_preferences"]

    assert isinstance(available, list)
    assert isinstance(preferences, list)
    assert [item["activity_type"] for item in available] == [
        "conversation_with_user",
        "plugin_activity",
        "topic_exploration",
    ]
    assert [item["activity_type"] for item in preferences] == [
        "conversation_with_user",
        "plugin_activity",
        "topic_exploration",
    ]
    assert planning_input["motivation"]["primary_desire"] == "autonomy"
    assert all(
        item["activity_type"] != "unknown_activity" for item in available
    )
    assert "意味的に妥当な候補が複数ある場合" in prompt
    assert "Authority・Capability・Constraint" in prompt


class _ConversationMatcher:
    def match(
        self,
        context: ActivityMatcherContext,
    ) -> DeterministicActivityMatch | None:
        if context.normalized_input != "話そう":
            return None
        return DeterministicActivityMatch(
            operation=ActivityOperation.START,
            goal="会話を始める",
            constraints={},
            confidence=1.0,
            reason="explicit_conversation_match",
            matcher_id="conversation_matcher",
            matcher_type="runtime",
            priority=500,
        )


class _FailIfCalledModel:
    def __init__(self) -> None:
        self.called = False

    async def evaluate(self, activity: object) -> str:
        self.called = True
        raise AssertionError("決定論Matcher成立時にLLMを呼び出してはいけません。")


@pytest.mark.asyncio
async def test_motivation_does_not_override_deterministic_matcher() -> None:
    model = _FailIfCalledModel()
    definitions = (
        _definition("plugin_activity"),
        _definition("conversation_with_user", matcher=_ConversationMatcher()),
    )
    context = BehaviorPlanningContext(
        user_text="話そう",
        source_event_id="event-2",
        available_capabilities=frozenset(),
        activity_definitions=definitions,
        motivation={
            "primary_desire": "autonomy",
            "recommended_activity_types": ["plugin_activity"],
        },
    )

    analysis = await SituationEvaluator(
        model,
        prompt_builder=SituationEvaluatorPromptBuilder(),
    ).evaluate(context)

    assert analysis.activity_candidate == "conversation_with_user"
    assert analysis.reason == "explicit_conversation_match"
    assert model.called is False
