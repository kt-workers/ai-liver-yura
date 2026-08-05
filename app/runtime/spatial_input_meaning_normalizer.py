from __future__ import annotations

import re
from dataclasses import replace

from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    StructuredInputMeaning,
)
from app.runtime.avatar_body_command_normalizer import (
    normalize_avatar_body_command,
)

_SPATIAL_SPEECH_ACTS = {
    InputSpeechAct.COMMAND,
    InputSpeechAct.REQUEST,
    InputSpeechAct.PROPOSAL,
}

_DIRECTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "up_right",
        (
            "右上",
            "上右",
            "upper right",
            "top right",
            "up-right",
            "right-up",
        ),
    ),
    (
        "up_left",
        (
            "左上",
            "上左",
            "upper left",
            "top left",
            "up-left",
            "left-up",
        ),
    ),
    (
        "down_right",
        (
            "右下",
            "下右",
            "lower right",
            "bottom right",
            "down-right",
            "right-down",
        ),
    ),
    (
        "down_left",
        (
            "左下",
            "下左",
            "lower left",
            "bottom left",
            "down-left",
            "left-down",
        ),
    ),
    ("center", ("正面", "真正面", "中央", "まっすぐ前", "front", "center", "centre")),
    ("right", ("右", "right")),
    ("left", ("左", "left")),
    ("up", ("上", "up", "above")),
    ("down", ("下", "down", "below")),
)

_ORIENTATION_MARKERS = (
    "向いて",
    "向く",
    "向けて",
    "振り向",
    "顔を向",
    "turn",
    "face",
    "orient",
)
_GAZE_MARKERS = (
    "見て",
    "見る",
    "視線",
    "目を向",
    "look",
    "gaze",
    "watch",
)


def normalize_spatial_input_meaning(
    meaning: StructuredInputMeaning,
) -> StructuredInputMeaning:
    """身体Motionまたは視線・向きの指示をInputTargetへ正規化する。"""

    if meaning.expected_response is not ExpectedResponse.ACTION:
        return meaning
    if meaning.input_speech_act not in _SPATIAL_SPEECH_ACTS:
        return meaning

    # 「右手を上げる」の「右」「上」などを視線方向として誤認しないよう、
    # BodyMotionRequestへの変換を方向語より先に確定する。
    body_motion = normalize_avatar_body_command(meaning)
    if (
        body_motion.target is not None
        and body_motion.target.target_type.casefold() == "body_motion"
    ):
        return body_motion

    existing = _normalize_existing_target(meaning.target)
    if existing is not None:
        return replace(meaning, target=existing)

    text = _meaning_text(meaning)
    direction = canonical_spatial_direction(text)
    mode = spatial_attention_mode(text)
    if direction is not None and mode is not None:
        return replace(
            meaning,
            target=InputTarget(
                target_type=(
                    "orientation_direction" if mode == "orientation" else "gaze_direction"
                ),
                target_id=direction,
            ),
        )
    return meaning


def canonical_spatial_direction(text: str) -> str | None:
    normalized = _normalize_text(text)
    for direction, patterns in _DIRECTION_PATTERNS:
        if any(_contains_pattern(normalized, pattern) for pattern in patterns):
            return direction
    return None


def spatial_attention_mode(text: str) -> str | None:
    normalized = _normalize_text(text)
    if any(marker in normalized for marker in _ORIENTATION_MARKERS):
        return "orientation"
    if any(marker in normalized for marker in _GAZE_MARKERS):
        return "gaze"
    return None


def _normalize_existing_target(target: InputTarget | None) -> InputTarget | None:
    if target is None:
        return None
    direction = canonical_spatial_direction(target.target_id)
    if direction is None:
        return None
    target_type = target.target_type.strip().lower()
    if target_type in {
        "orientation",
        "orientation_direction",
        "body_direction",
        "facing_direction",
    }:
        return InputTarget("orientation_direction", direction)
    if target_type in {
        "gaze",
        "gaze_direction",
        "look_direction",
        "spatial_direction",
        "direction",
    }:
        return InputTarget("gaze_direction", direction)
    return None


def _meaning_text(meaning: StructuredInputMeaning) -> str:
    parts = [meaning.source_text, meaning.primary_intent]
    parts.extend(meaning.information_provided)
    for collection in (meaning.entities, meaning.references):
        for item in collection:
            parts.extend(str(value) for value in item.values() if value is not None)
    return " ".join(part for part in parts if part)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _contains_pattern(text: str, pattern: str) -> bool:
    normalized_pattern = pattern.lower()
    if normalized_pattern.isascii() and normalized_pattern.isalpha():
        return re.search(rf"\b{re.escape(normalized_pattern)}\b", text) is not None
    return normalized_pattern in text
