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
    (
        "right_hand_lower",
        (
            "右手を下に下ろ",
            "右手を下におろ",
            "右手を下ろ",
            "右手をおろ",
            "右腕を下に下ろ",
            "右腕を下におろ",
            "右腕を下ろ",
            "右腕をおろ",
        ),
    ),
    (
        "left_hand_lower",
        (
            "左手を下に下ろ",
            "左手を下におろ",
            "左手を下ろ",
            "左手をおろ",
            "左腕を下に下ろ",
            "左腕を下におろ",
            "左腕を下ろ",
            "左腕をおろ",
        ),
    ),
    (
        "both_hands_lower",
        (
            "両手を下に下ろ",
            "両手を下におろ",
            "両手を下ろ",
            "両手をおろ",
            "両腕を下に下ろ",
            "両腕を下におろ",
            "両腕を下ろ",
            "両腕をおろ",
            "腕を下に下ろ",
            "腕を下におろ",
            "腕を下ろ",
            "腕をおろ",
        ),
    ),
    (
        "right_leg_raise",
        ("右足を挙げ", "右足を上げ", "右脚を挙げ", "右脚を上げ"),
    ),
    (
        "left_leg_raise",
        ("左足を挙げ", "左足を上げ", "左脚を挙げ", "左脚を上げ"),
    ),
    ("right_hand_raise", ("右手を挙げ", "右手を上げ", "右腕を挙げ", "右腕を上げ")),
    ("left_hand_raise", ("左手を挙げ", "左手を上げ", "左腕を挙げ", "左腕を上げ")),
    ("both_hands_raise", ("両手を挙げ", "両手を上げ", "両腕を挙げ", "両腕を上げ")),
    ("right_hand_wave", ("右手を振って", "右手を振る", "右手でバイバイ")),
    ("left_hand_wave", ("左手を振って", "左手を振る", "左手でバイバイ")),
    ("both_hands_wave", ("両手を振って", "両手を振る", "両手でバイバイ")),
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
