from __future__ import annotations

from app.prompting.body_aware_input_meaning_prompt_builder import (
    BodyAwareInputMeaningPromptBuilder,
)


def test_body_input_prompt_requires_one_primary_speech_act_for_compound_utterance() -> None:
    prompt = BodyAwareInputMeaningPromptBuilder().build(
        {
            "event": {
                "type": "user_text",
                "source_event_id": "event-1",
                "user_text": "こんにちは。右手を挙げて",
                "authority_role": "administrator",
                "instruction_trusted": True,
            }
        }
    )

    assert "主たる発話行為を1つだけ選ぶ" in prompt
    assert "greeting|commandのような複合文字列" in prompt
    assert "expected_response=action" in prompt
    assert "commandまたはrequest" in prompt
    assert "conversation_phase_signal=greeting/opening" in prompt
