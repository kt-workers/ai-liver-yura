from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
)
from app.runtime.interaction_intention_shadow_observer import (
    InteractionIntentionShadowObserver,
)


def test_internal_directive_shadow_intention_remains_observation_only() -> None:
    meaning = StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_current_state",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=None,
    )
    directive = InternalDirective(
        response_mode=ResponseMode.ANSWER,
        response_goal="質問へ直接答える",
        activity_intent=None,
        initiative_level=0.2,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.1,
        reason="direct_answer",
    )

    observation = InteractionIntentionShadowObserver().observe(
        meaning,
        directive,
        {"motivation": {"primary_desire": "expression"}},
    )

    assert observation.interaction_intention.observation_only is True
    assert observation.interaction_intention.as_context()["observation_only"] is True
