from __future__ import annotations

from dataclasses import replace

from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    StructuredInputMeaning,
)

_ACTION_SPEECH_ACTS = {
    InputSpeechAct.COMMAND,
    InputSpeechAct.REQUEST,
    InputSpeechAct.PROPOSAL,
}

_ACTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("right_hand_raise", ("右手を挙げ", "右手を上げ", "右腕を挙げ", "右腕を上げ")),
    ("left_hand_raise", ("左手を挙げ", "左手を上げ", "左腕を挙げ", "左腕を上げ")),
    ("both_hands_raise", ("両手を挙げ", "両手を上げ", "両腕を挙げ", "両腕を上げ")),
    ("right_hand_wave", ("右手を振って", "右手を振る")),
    ("left_hand_wave", ("左手を振って", "左手を振る")),
    ("both_hands_wave", ("両手を振って", "両手を振る")),
    ("eyes_close", ("目を閉じ", "眼を閉じ", "両目を閉じ", "瞼を閉じ")),
    ("eyes_open", ("目を開け", "眼を開け", "両目を開け", "瞼を開け")),
    ("blink", ("まばたきして", "瞬きして")),
    ("mouth_open", ("口を開け", "口開け")),
    ("mouth_close", ("口を閉じ", "口閉じ")),
    ("head_circle", ("顔をぐるっと回", "頭をぐるっと回", "首をぐるっと回")),
    ("bow", ("お辞儀して", "おじぎして", "頭を下げて")),
    ("jump", ("ジャンプして", "飛び跳ねて", "跳んで")),
    ("body_sway", ("体を左右に揺ら", "身体を左右に揺ら", "体を揺らして")),
    ("body_twist", ("体をひねって", "身体をひねって", "胴体をひねって")),
)


def normalize_avatar_body_command(
    meaning: StructuredInputMeaning,
) -> StructuredInputMeaning:
    if meaning.expected_response is not ExpectedResponse.ACTION:
        return meaning
    if meaning.input_speech_act not in _ACTION_SPEECH_ACTS:
        return meaning

    if meaning.target is not None:
        target_type = meaning.target.target_type.casefold()
        if target_type in {"avatar_body_action", "body_action", "avatar_action"}:
            return replace(
                meaning,
                target=InputTarget("avatar_body_action", meaning.target.target_id),
            )
        if target_type in {"activity", "plugin", "subsystem", "topic"}:
            return meaning

    text = _meaning_text(meaning)
    for action, patterns in _ACTION_PATTERNS:
        if any(pattern in text for pattern in patterns):
            return replace(
                meaning,
                target=InputTarget("avatar_body_action", action),
            )
    return meaning


def _meaning_text(meaning: StructuredInputMeaning) -> str:
    parts = [meaning.source_text, meaning.primary_intent]
    parts.extend(meaning.information_provided)
    for collection in (meaning.entities, meaning.references):
        for item in collection:
            parts.extend(str(value) for value in item.values() if value is not None)
    return " ".join(part for part in parts if part).casefold()
