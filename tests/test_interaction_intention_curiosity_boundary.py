from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    StructuredInputMeaning,
)
from app.domain.interaction_intention import InteractionIntentionType
from app.runtime.interaction_intention_appraiser import (
    InteractionIntentionAppraiser,
)


def test_global_curiosity_without_target_gap_prefers_observation() -> None:
    meaning = StructuredInputMeaning(
        input_speech_act=InputSpeechAct.STATEMENT,
        primary_intent="observe_new_topic",
        expected_response=ExpectedResponse.CLARIFICATION,
        target=None,
    )

    intention = InteractionIntentionAppraiser().appraise(
        meaning,
        {"motivation": {"primary_desire": "curiosity"}},
    )

    assert intention.intention is InteractionIntentionType.OBSERVE
    assert intention.reason == "global_curiosity_does_not_authorize_question"
    assert intention.requires_response is True
