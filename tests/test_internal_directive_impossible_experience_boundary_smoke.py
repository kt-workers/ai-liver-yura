from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    StructuredInputMeaning,
)
from app.runtime.internal_directive_validator import InternalDirectiveValidator


def test_physical_experience_is_not_declared_impossible_without_boundary() -> None:
    meaning = StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_physical_experience",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget("character_experience", "yesterday_outing"),
        past_reference=True,
    )

    assert (
        InternalDirectiveValidator._is_impossible_embodied_experience(
            meaning,
            ("現実世界で活動できる身体を持つ",),
        )
        is False
    )
