from __future__ import annotations

from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    StructuredInputMeaning,
)
from app.prompting.cognitive_direction_prompt_builders import (
    InternalDirectivePromptBuilder,
)


def test_multi_preset_prompt_builds_without_error() -> None:
    meaning = StructuredInputMeaning(
        input_speech_act=InputSpeechAct.REQUEST,
        primary_intent="continue_previous_explanation",
        expected_response=ExpectedResponse.ACTION,
        target=InputTarget("activity", "directive_explanation"),
        confidence=0.98,
    )
    prompt = InternalDirectivePromptBuilder().build(
        meaning,
        {
            "emotion": {"joy": 0.4},
            "drive": {"curiosity": 0.7},
            "relationship": {},
            "motivation": {},
            "moral": {},
            "situation": {},
            "memory": {},
            "related_knowledge": [],
            "last_activity_result": None,
            "ongoing_activity": {
                "activity_type": "conversation",
                "goal": "説明を続ける",
            },
            "available_activities": [
                {
                    "activity_type": "conversation",
                    "operations": ["continue"],
                }
            ],
        },
        character_profile={
            "name": "ゆら",
            "existence": {
                "physical_capabilities": ["物理的な身体を持たない"]
            },
        },
    )

    assert "# DirectiveInput" in prompt
    assert '"operation": "start|continue|stop|explain|discuss"' in prompt
