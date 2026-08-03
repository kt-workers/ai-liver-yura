from __future__ import annotations

import json

import pytest

from app.domain.activities import Activity, ActivityType
from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
)
from app.runtime.cognitive_direction_services import InternalDirectivePlanner
from app.runtime.internal_directive_candidate_normalizer import (
    InternalDirectiveCandidateNormalizer,
)


class _PromptBuilder:
    def build(
        self,
        meaning: StructuredInputMeaning,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> str:
        del meaning, planning_input, character_profile
        return "prompt"


class _Model:
    async def plan_internal_directive(self, activity: Activity) -> str:
        del activity
        return json.dumps(
            {
                "response_mode": "react",
                "response_goal": "短く共感する",
                "activity_intent": None,
                "initiative_level": 0.2,
                "question_budget": 0,
                "new_direction_budget": 0,
                "self_disclosure_level": 0.1,
                "content_requirements": [
                    "ユーザーの喜びに短く共感する",
                    "現実空間での実体験を語らない",
                ],
                "forbidden_claims": [
                    "質問を追加する",
                    "身体的・現実空間での実体験を語る",
                ],
                "target_interest_updates": [],
                "state_update_proposals": [],
                "reason": "共感反応が適切",
            },
            ensure_ascii=False,
        )


def _positive_meaning() -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=InputSpeechAct.STATEMENT,
        primary_intent="share_positive_experience",
        expected_response=ExpectedResponse.ACKNOWLEDGEMENT,
        target=InputTarget("user_experience", "positive_event"),
        confidence=0.98,
    )


def _physical_meaning() -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_physical_experience",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget("character_experience", "yesterday_outing"),
        past_reference=True,
        confidence=0.98,
    )


def _directive() -> InternalDirective:
    return InternalDirective(
        response_mode=ResponseMode.REACT,
        response_goal="短く反応する",
        activity_intent=None,
        initiative_level=0.2,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.1,
        content_requirements=(
            "入力内容へ簡潔に反応する",
            "現実世界での実体験を語らない",
        ),
        forbidden_claims=(
            "質問を追加する",
            "存在境界を超える実体験の主張",
        ),
    )


def test_nonphysical_input_removes_generic_existence_constraints() -> None:
    normalized = InternalDirectiveCandidateNormalizer().normalize(
        _positive_meaning(),
        _directive(),
    )

    assert normalized.content_requirements == ("入力内容へ簡潔に反応する",)
    assert normalized.forbidden_claims == ("質問を追加する",)


def test_physical_experience_input_preserves_existence_constraints() -> None:
    directive = _directive()

    normalized = InternalDirectiveCandidateNormalizer().normalize(
        _physical_meaning(),
        directive,
    )

    assert normalized is directive
    assert "現実世界での実体験を語らない" in normalized.content_requirements
    assert "存在境界を超える実体験の主張" in normalized.forbidden_claims


@pytest.mark.asyncio
async def test_planner_returns_normalized_candidate() -> None:
    planner = InternalDirectivePlanner(
        _Model(),
        prompt_builder=_PromptBuilder(),
    )
    activity = Activity(
        activity_type=ActivityType.BEHAVIOR_PLANNING,
        goal="test",
        context={},
        source_event_id="event-1",
    )

    directive = await planner.plan(
        activity,
        _positive_meaning(),
        {},
        character_profile={},
    )

    assert directive is not None
    assert directive.content_requirements == ("ユーザーの喜びに短く共感する",)
    assert directive.forbidden_claims == ("質問を追加する",)
