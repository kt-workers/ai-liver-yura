from __future__ import annotations

import json

import pytest

from app.domain.activities import Activity, ActivityType
from app.domain.cognitive_direction import (
    ConversationPhaseSignal,
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


class _CuriosityModel:
    async def plan_internal_directive(self, activity: Activity) -> str:
        del activity
        return json.dumps(
            {
                "response_mode": "react",
                "response_goal": "興味深い話題へ短く反応する",
                "activity_intent": None,
                "initiative_level": 0.28,
                "question_budget": 0,
                "new_direction_budget": 0,
                "self_disclosure_level": 0.1,
                "content_requirements": [
                    "入力内容へ簡潔に反応する",
                    "新しい問いかけや話題の拡張はしない",
                ],
                "forbidden_claims": ["質問を追加しない"],
                "target_interest_updates": [],
                "state_update_proposals": [],
                "reason": "acknowledgementとして処理する",
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


def _curious_meaning() -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=InputSpeechAct.STATEMENT,
        primary_intent="share_interesting_topic",
        expected_response=ExpectedResponse.ACKNOWLEDGEMENT,
        target=InputTarget("topic", "deep_sea_unknown_life"),
        conversation_phase_signal=ConversationPhaseSignal.CONTINUE,
        confidence=0.96,
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


def _curious_input(
    *,
    curiosity: float = 0.94,
    engagement: float = 0.91,
    target_id: str = "deep_sea_unknown_life",
) -> dict[str, object]:
    return {
        "drive": {"curiosity": curiosity},
        "motivation": {"engagement": engagement},
        "related_knowledge": [
            {
                "target_type": "topic",
                "target_id": target_id,
                "interest": 0.94,
                "knowledge_gaps": [
                    "未発見生物が多いと考えられている深度や環境"
                ],
            }
        ],
    }


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


def test_matching_target_gap_and_high_motivation_restore_single_question() -> None:
    directive = InternalDirective(
        response_mode=ResponseMode.REACT,
        response_goal="話題へ短く反応する",
        activity_intent=None,
        initiative_level=0.28,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.1,
        content_requirements=(
            "新しい問いかけや話題の拡張はしない",
        ),
        forbidden_claims=("質問を追加しない",),
    )

    normalized = InternalDirectiveCandidateNormalizer().normalize(
        _curious_meaning(),
        directive,
        _curious_input(),
    )

    assert normalized.response_mode is ResponseMode.ASK
    assert normalized.question_budget == 1
    assert normalized.new_direction_budget == 0
    assert normalized.initiative_level == 0.35
    assert "質問を追加しない" not in normalized.forbidden_claims
    requirements = "\n".join(normalized.content_requirements)
    assert "未発見生物が多いと考えられている深度や環境" in requirements
    assert "質問を1件だけ" in requirements
    assert "無関係な新しい話題へ展開しない" in requirements


@pytest.mark.parametrize(
    ("planning_input", "meaning"),
    (
        (_curious_input(curiosity=0.2, engagement=0.3), _curious_meaning()),
        (_curious_input(target_id="another_topic"), _curious_meaning()),
        (
            _curious_input(),
            StructuredInputMeaning(
                input_speech_act=InputSpeechAct.CLOSING,
                primary_intent="end_conversation",
                expected_response=ExpectedResponse.NO_RESPONSE,
                target=InputTarget("topic", "deep_sea_unknown_life"),
                conversation_phase_signal=ConversationPhaseSignal.WINDING_DOWN,
                confidence=0.99,
            ),
        ),
    ),
)
def test_question_is_not_restored_without_all_required_signals(
    planning_input: dict[str, object],
    meaning: StructuredInputMeaning,
) -> None:
    directive = _directive()

    normalized = InternalDirectiveCandidateNormalizer().normalize(
        meaning,
        directive,
        planning_input,
    )

    assert normalized.response_mode is ResponseMode.REACT
    assert normalized.question_budget == 0


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


@pytest.mark.asyncio
async def test_planner_passes_planning_input_to_question_normalizer() -> None:
    planner = InternalDirectivePlanner(
        _CuriosityModel(),
        prompt_builder=_PromptBuilder(),
    )
    activity = Activity(
        activity_type=ActivityType.BEHAVIOR_PLANNING,
        goal="test",
        context={},
        source_event_id="event-2",
    )

    directive = await planner.plan(
        activity,
        _curious_meaning(),
        _curious_input(),
        character_profile={},
    )

    assert directive is not None
    assert directive.response_mode is ResponseMode.ASK
    assert directive.question_budget == 1
    assert directive.new_direction_budget == 0
