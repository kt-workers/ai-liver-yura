from __future__ import annotations

import json
from typing import cast

import pytest

from app.domain.activities import Activity, ActivityType
from app.domain.cognitive_direction import (
    ActivityIntent,
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
)
from app.domain.interaction_intention import InteractionIntentionType
from app.runtime.cognitive_direction_services import InternalDirectivePlanner
from app.runtime.interaction_intention_appraiser import (
    InteractionIntentionAppraiser,
)
from app.runtime.interaction_intention_shadow_observer import (
    InteractionIntentionShadowObserver,
)
from app.utils.trace import TraceLogger


class _RecordingTraceLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, object]]] = []

    def info(self, label: str, **values: object) -> None:
        self.records.append((label, values))


class _DirectiveModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[Activity] = []

    async def plan_internal_directive(self, activity: Activity) -> str:
        self.requests.append(activity)
        return json.dumps(self.payload, ensure_ascii=False)


class _PromptBuilder:
    def build(
        self,
        meaning: StructuredInputMeaning,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> str:
        return "interaction intention shadow prompt"


def _meaning(
    *,
    speech_act: InputSpeechAct = InputSpeechAct.STATEMENT,
    expected: ExpectedResponse = ExpectedResponse.ACKNOWLEDGEMENT,
    intent: str = "provide_information",
    target: InputTarget | None = None,
    source_text: str = "",
) -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=speech_act,
        primary_intent=intent,
        expected_response=expected,
        target=target,
        source_text=source_text,
    )


def _directive(
    mode: ResponseMode,
    *,
    goal: str = "入力へ応答する",
    activity_intent: ActivityIntent | None = None,
) -> InternalDirective:
    return InternalDirective(
        response_mode=mode,
        response_goal=goal,
        activity_intent=activity_intent,
        initiative_level=0.3,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.2,
        reason="test_directive",
    )


def _directive_payload(mode: str = "answer") -> dict[str, object]:
    return {
        "response_mode": mode,
        "response_goal": "質問へ直接答える",
        "activity_intent": None,
        "initiative_level": 0.3,
        "question_budget": 0,
        "new_direction_budget": 0,
        "self_disclosure_level": 0.2,
        "content_requirements": [],
        "forbidden_claims": [],
        "target_interest_updates": [],
        "state_update_proposals": [],
        "reason": "direct_question",
    }


def test_direct_question_produces_answer_and_exact_shadow_match() -> None:
    meaning = _meaning(
        speech_act=InputSpeechAct.QUESTION,
        expected=ExpectedResponse.DIRECT_ANSWER,
        intent="ask_current_feeling",
        target=InputTarget("internal_state", "current_emotion"),
    )

    observation = InteractionIntentionShadowObserver().observe(
        meaning,
        _directive(ResponseMode.ANSWER),
        {"motivation": {"primary_desire": "expression"}},
    )

    assert observation.interaction_intention.intention is InteractionIntentionType.ANSWER
    assert observation.comparison.exact_match is True
    assert observation.comparison.compatible is True


def test_action_obligation_does_not_select_execution_permission() -> None:
    meaning = _meaning(
        speech_act=InputSpeechAct.REQUEST,
        expected=ExpectedResponse.ACTION,
        intent="continue_activity",
        target=InputTarget("activity", "topic_exploration"),
    )
    directive = _directive(
        ResponseMode.OBSERVE,
        activity_intent=ActivityIntent(
            "topic_exploration",
            "continue",
            {"maintain_current_goal": True},
        ),
    )

    observation = InteractionIntentionShadowObserver().observe(
        meaning,
        directive,
        {"motivation": {"primary_desire": "achievement"}},
    )

    intention = observation.interaction_intention
    assert intention.intention is InteractionIntentionType.ACT
    assert intention.activity_type == "topic_exploration"
    assert intention.operation == "continue"
    assert not hasattr(intention, "authorized")
    assert not hasattr(intention, "capability")
    assert observation.comparison.exact_match is True


def test_global_curiosity_without_target_gap_prefers_observe_not_question() -> None:
    meaning = _meaning(
        expected=ExpectedResponse.ACKNOWLEDGEMENT,
        intent="notice_topic",
    )

    intention = InteractionIntentionAppraiser().appraise(
        meaning,
        {
            "motivation": {
                "primary_desire": "curiosity",
                "recommended_conversation_strategies": ["ask_for_detail"],
            }
        },
    )

    assert intention.intention is InteractionIntentionType.ACKNOWLEDGE

    neutral_meaning = _meaning(
        expected=ExpectedResponse.NO_RESPONSE,
        intent="observe_environment",
    )
    neutral_intention = InteractionIntentionAppraiser().appraise(
        neutral_meaning,
        {"motivation": {"primary_desire": "curiosity"}},
    )
    assert neutral_intention.intention is InteractionIntentionType.PAUSE


def test_target_specific_gap_authorizes_single_ask_intention() -> None:
    meaning = _meaning(
        expected=ExpectedResponse.CLARIFICATION,
        intent="explore_known_gap",
        target=InputTarget("topic", "deep_sea_pressure_adaptation"),
    )

    intention = InteractionIntentionAppraiser().appraise(
        meaning,
        {
            "motivation": {"primary_desire": "curiosity"},
            "related_knowledge": [
                {
                    "target_type": "topic",
                    "target_id": "deep_sea_pressure_adaptation",
                    "unresolved_knowledge_gaps": ["細胞膜の具体的構造"],
                }
            ],
        },
    )

    assert intention.intention is InteractionIntentionType.ASK
    assert intention.reason == "target_specific_gap_authorizes_question"


def test_security_motivation_and_discomfort_produce_boundary_intention() -> None:
    meaning = _meaning(
        expected=ExpectedResponse.CLARIFICATION,
        intent="respond_to_repeated_uncomfortable_contact",
    )
    planning_input = {
        "motivation": {"primary_desire": "security"},
        "emotion": {
            "reactive": {
                "discomfort": 0.72,
                "emotional_pressure": 0.48,
            }
        },
    }

    observation = InteractionIntentionShadowObserver().observe(
        meaning,
        _directive(ResponseMode.SPEAK, goal="境界を伝えて接触をやめてと頼む"),
        planning_input,
    )

    assert (
        observation.interaction_intention.intention
        is InteractionIntentionType.SET_BOUNDARY
    )
    assert observation.comparison.exact_match is True


@pytest.mark.asyncio
async def test_internal_directive_planner_preserves_legacy_return_and_exposes_observation() -> None:
    meaning = _meaning(
        speech_act=InputSpeechAct.QUESTION,
        expected=ExpectedResponse.DIRECT_ANSWER,
        intent="ask_current_feeling",
    )
    model = _DirectiveModel(_directive_payload())
    planner = InternalDirectivePlanner(
        model,
        prompt_builder=cast(object, _PromptBuilder()),
    )
    activity = Activity(
        activity_type=ActivityType.BEHAVIOR_PLANNING,
        goal="内部指示を作る",
    )
    planning_input = {
        "motivation": {"primary_desire": "expression"},
        "emotion": {"valence": 0.1},
    }

    observation = await planner.plan_with_observation(
        activity,
        meaning,
        planning_input,
        character_profile={},
    )
    directive = await planner.plan(
        activity,
        meaning,
        planning_input,
        character_profile={},
    )

    assert observation is not None
    assert observation.directive.response_mode is ResponseMode.ANSWER
    assert observation.interaction_intention.intention is InteractionIntentionType.ANSWER
    assert observation.comparison.exact_match is True
    assert directive is not None
    assert directive.response_mode is ResponseMode.ANSWER
    assert model.requests[-1].context["llm_role"] == "internal_directive_planner"


def test_shadow_trace_does_not_copy_raw_user_text() -> None:
    raw_text = "この入力本文はInteraction Intention Traceへ複製しない"
    meaning = _meaning(
        expected=ExpectedResponse.ACKNOWLEDGEMENT,
        source_text=raw_text,
    )
    trace = _RecordingTraceLogger()
    observer = InteractionIntentionShadowObserver(
        trace_logger=cast(TraceLogger, trace)
    )

    observer.observe(
        meaning,
        _directive(ResponseMode.REACT),
        {"event": {"user_text": raw_text}},
    )

    label, values = trace.records[-1]
    assert label == "interaction_intention:shadow_compared"
    assert raw_text not in repr(values)
    assert "user_text" not in values
