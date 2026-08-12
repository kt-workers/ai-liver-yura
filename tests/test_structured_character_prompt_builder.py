from __future__ import annotations

from app.domain.character import CharacterProfile
from app.domain.semantic_utterance_v2 import (
    SemanticPropositionV2,
    SemanticUtterancePlanV2,
    SemanticValue,
)
from app.prompting.structured_character_prompt_builder import (
    StructuredCharacterPromptBuilder,
)


def _plan() -> SemanticUtterancePlanV2:
    return SemanticUtterancePlanV2(
        speech_act="answer",
        propositions=(
            SemanticPropositionV2(
                proposition_id="p1",
                kind="internal_state",
                predicate="joy",
                value=SemanticValue(
                    status="known",
                    polarity="present",
                    degree="high",
                    certainty="medium",
                ),
                realization_policy="required",
            ),
        ),
    )


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="好奇心がある",
        speaking_style="自然体",
        streaming_style="落ち着いた雑談",
    )


def test_prompt_contains_role_plan_profile_and_short_rules_without_schema() -> None:
    prompt = StructuredCharacterPromptBuilder().build(
        character_profile=_profile(),
        plan=_plan(),
        user_wording_hint="今どんな気分？",
    )

    assert "Role: Character Language Realizer" in prompt
    assert '"proposition_id":"p1"' in prompt
    assert '"name":"ゆら"' in prompt
    assert "今どんな気分？" in prompt
    assert "required propositionは必ず自然なspeechへ表現する" in prompt
    assert "Character Profileは言い方だけに使う" in prompt
    assert "JSON Schema" not in prompt
    assert '"additionalProperties"' not in prompt


def test_user_wording_hint_is_bounded() -> None:
    builder = StructuredCharacterPromptBuilder()
    hint = "あ" * (builder.USER_WORDING_HINT_LIMIT + 50)

    prompt = builder.build(
        character_profile=_profile(),
        plan=_plan(),
        user_wording_hint=hint,
    )

    assert "あ" * builder.USER_WORDING_HINT_LIMIT in prompt
    assert "あ" * (builder.USER_WORDING_HINT_LIMIT + 1) not in prompt


def test_typed_regeneration_differences_are_optional() -> None:
    builder = StructuredCharacterPromptBuilder()

    without = builder.build(character_profile=_profile(), plan=_plan())
    with_differences = builder.build(
        character_profile=_profile(),
        plan=_plan(),
        regeneration_differences={
            "p1": {
                "certainty_relation": "weaker",
            }
        },
    )

    assert "Typed Regeneration Differences" not in without
    assert "Typed Regeneration Differences" in with_differences
    assert '"certainty_relation":"weaker"' in with_differences
