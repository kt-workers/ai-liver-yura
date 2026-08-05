from __future__ import annotations

import math
import re
from dataclasses import replace
from typing import Iterable, Mapping

from app.domain.activities import Activity
from app.domain.body_motion import (
    BodyMotionOperation,
    BodyMotionRequest,
    BodyMotionTiming,
    BodyMotionVector,
)
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

_TARGET_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("both_hands", ("両手", "両腕", "both hands", "both arms")),
    ("right_hand", ("右手", "右腕", "right hand", "right arm")),
    ("left_hand", ("左手", "左腕", "left hand", "left arm")),
    ("both_ankles", ("両足", "両脚", "both feet", "both legs")),
    ("right_ankle", ("右足", "右脚", "right foot", "right leg")),
    ("left_ankle", ("左足", "左脚", "left foot", "left leg")),
    ("head", ("頭", "顔", "首", "head", "face", "neck")),
    ("chest", ("胸", "上半身", "胴体", "body", "torso", "chest")),
    ("pelvis", ("腰", "骨盤", "hips", "pelvis", "waist")),
    ("root", ("全身", "体全体", "whole body", "entire body")),
)

_SEQUENCE_MARKERS = re.compile(r"(?:してから|した後|その後|次に|それから|\bthen\b)")
_DURATION_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?:秒|seconds?|sec)")
_REPETITION_PATTERN = re.compile(r"(?P<value>\d+)\s*(?:回|times?)")
_COORDINATE_PATTERN = re.compile(
    r"(?P<axis>[xyzXYZ])\s*[=:]\s*(?P<value>-?\d+(?:\.\d+)?)"
)


class BodyMotionRequestResolver:
    """Activityの構造化意味からモデル非依存の運動要求を取り出す。"""

    def resolve(self, activity: Activity) -> BodyMotionRequest | None:
        meaning = self._structured_input_meaning(activity)
        if meaning is None:
            return None
        return body_motion_request_from_context(meaning)

    @classmethod
    def _structured_input_meaning(
        cls,
        activity: Activity,
    ) -> dict[str, object] | None:
        candidates: list[object] = [activity.context]
        event_payload = activity.context.get("event_payload")
        if isinstance(event_payload, dict):
            candidates.append(event_payload)
        constraints = activity.context.get("constraints")
        if isinstance(constraints, dict):
            candidates.append(constraints)
        for candidate in candidates:
            found = cls._find_meaning(candidate)
            if found is not None:
                return found
        return None

    @classmethod
    def _find_meaning(cls, value: object) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        direct = value.get("structured_input_meaning")
        if isinstance(direct, dict):
            return dict(direct)
        internal = value.get("_internal_directive")
        if isinstance(internal, dict):
            nested = internal.get("structured_input_meaning")
            if isinstance(nested, dict):
                return dict(nested)
        for key in ("constraints", "behavior_plan", "event_payload"):
            nested = value.get(key)
            if isinstance(nested, dict):
                found = cls._find_meaning(nested)
                if found is not None:
                    return found
        return None


def normalize_body_motion_meaning(
    meaning: StructuredInputMeaning,
) -> StructuredInputMeaning:
    """身体指示を名前付き動作ではなくBodyMotionRequestへ正規化する。"""

    if meaning.expected_response is not ExpectedResponse.ACTION:
        return meaning
    if meaning.input_speech_act not in _ACTION_SPEECH_ACTS:
        return meaning
    request = body_motion_request_from_meaning(meaning)
    if request is None:
        return meaning
    entity = {
        "type": "body_motion_request",
        "payload": request.as_payload(),
    }
    remaining_entities = tuple(
        item
        for item in meaning.entities
        if str(item.get("type", "")).strip().lower()
        != "body_motion_request"
    )
    return replace(
        meaning,
        target=InputTarget("body_motion", request.operation.value),
        entities=(*remaining_entities, entity),
    )


def body_motion_request_from_meaning(
    meaning: StructuredInputMeaning,
) -> BodyMotionRequest | None:
    explicit = _explicit_request((*meaning.entities, *meaning.references))
    if explicit is not None:
        return explicit
    return _request_from_text(_meaning_text(meaning))


def body_motion_request_from_context(
    meaning: Mapping[str, object],
) -> BodyMotionRequest | None:
    if str(meaning.get("expected_response", "")).strip().lower() != "action":
        return None
    if str(meaning.get("input_speech_act", "")).strip().lower() not in {
        "command",
        "request",
        "proposal",
    }:
        return None
    collections: list[Mapping[str, object]] = []
    for key in ("entities", "references"):
        raw = meaning.get(key)
        if isinstance(raw, (list, tuple)):
            collections.extend(item for item in raw if isinstance(item, dict))
    explicit = _explicit_request(collections)
    if explicit is not None:
        return explicit
    parts = [
        str(meaning.get("source_text", "")),
        str(meaning.get("primary_intent", "")),
    ]
    information = meaning.get("information_provided")
    if isinstance(information, (list, tuple)):
        parts.extend(str(item) for item in information)
    for item in collections:
        parts.extend(str(value) for value in item.values() if value is not None)
    return _request_from_text(" ".join(part for part in parts if part))


def _explicit_request(
    items: Iterable[Mapping[str, object]],
) -> BodyMotionRequest | None:
    for item in items:
        candidates: list[object] = []
        item_type = str(item.get("type", "")).strip().lower()
        if item_type in {"body_motion_request", "motion_request", "body_motion"}:
            candidates.extend((item.get("payload"), item.get("request"), item))
        for key in ("body_motion_request", "motion_request", "body_motion"):
            candidates.append(item.get(key))
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            payload = dict(candidate)
            payload.pop("type", None)
            if "operation" not in payload:
                continue
            try:
                return BodyMotionRequest.from_payload(payload)
            except (TypeError, ValueError):
                continue
    return None


def _request_from_text(text: str) -> BodyMotionRequest | None:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if not normalized:
        return None
    clauses = [part.strip(" 、,。") for part in _SEQUENCE_MARKERS.split(normalized)]
    clauses = [part for part in clauses if part]
    if len(clauses) > 1:
        children = tuple(
            request
            for request in (_request_from_clause(clause) for clause in clauses)
            if request is not None
        )
        if len(children) > 1:
            return BodyMotionRequest(
                operation=BodyMotionOperation.SEQUENCE,
                children=children,
                timing=BodyMotionTiming(),
            )
    return _request_from_clause(normalized)


def _request_from_clause(text: str) -> BodyMotionRequest | None:
    targets = _targets(text)
    if not targets:
        return None
    timing = _timing(text)
    operation = _operation(text)
    requests = tuple(
        _primitive_request(operation, target, text, timing)
        for target in targets
    )
    if len(requests) == 1:
        return requests[0]
    return BodyMotionRequest(
        operation=BodyMotionOperation.PARALLEL,
        children=requests,
        timing=BodyMotionTiming(),
    )


def _targets(text: str) -> tuple[str, ...]:
    for target, patterns in _TARGET_PATTERNS:
        if not any(pattern in text for pattern in patterns):
            continue
        if target == "both_hands":
            return ("left_hand", "right_hand")
        if target == "both_ankles":
            return ("left_ankle", "right_ankle")
        return (target,)
    return ()


def _operation(text: str) -> BodyMotionOperation:
    if any(word in text for word in ("円", "ぐる", "circle", "orbit")):
        return BodyMotionOperation.CIRCLE
    if any(word in text for word in ("振", "揺", "oscillat", "wave")):
        return BodyMotionOperation.OSCILLATE
    if any(word in text for word in ("ひね", "回転", "rotate", "twist")):
        return BodyMotionOperation.ROTATE
    if any(word in text for word in ("ずら", "平行移動", "translate", "移動して")):
        return BodyMotionOperation.TRANSLATE
    return BodyMotionOperation.REACH


def _primitive_request(
    operation: BodyMotionOperation,
    target: str,
    text: str,
    timing: BodyMotionTiming,
) -> BodyMotionRequest:
    if operation is BodyMotionOperation.CIRCLE:
        return BodyMotionRequest(
            operation=operation,
            target=target,
            radius=_radius(text),
            axis=_axis(text),
            direction=_direction_sign(text),
            timing=timing,
        )
    if operation is BodyMotionOperation.ROTATE:
        return BodyMotionRequest(
            operation=operation,
            target=target,
            axis=_axis(text),
            amount=_rotation_amount(text),
            direction=_direction_sign(text),
            timing=timing,
        )
    vector = _vector(text, target=target, absolute=operation is BodyMotionOperation.REACH)
    return BodyMotionRequest(
        operation=operation,
        target=target,
        vector=vector,
        timing=timing,
    )


def _vector(text: str, *, target: str, absolute: bool) -> BodyMotionVector:
    coordinates = {match.group("axis").lower(): float(match.group("value")) for match in _COORDINATE_PATTERN.finditer(text)}
    if coordinates:
        return BodyMotionVector(
            coordinates.get("x", 0.0),
            coordinates.get("y", 0.0),
            coordinates.get("z", 0.0),
        )
    side = -1.0 if target.startswith("left_") else 1.0
    if target in {"head", "chest", "pelvis", "root"}:
        side = 0.0
    if absolute:
        x = side * 0.62
        y = 0.88 if "hand" in target else (-0.72 if "ankle" in target else 0.72)
        z = 0.0
        if any(word in text for word in ("上", "高く", "above", "up")):
            y = 1.25 if "hand" in target else 0.25
        if any(word in text for word in ("下", "低く", "below", "down")):
            y = 0.18 if "hand" in target else -1.0
        if any(word in text for word in ("前", "手前", "forward", "front")):
            z = 0.62
        if any(word in text for word in ("後ろ", "奥", "back", "behind")):
            z = -0.45
        if "中央" in text or "center" in text:
            x = 0.0
        return BodyMotionVector(x, y, z)
    x = 0.0
    y = 0.0
    z = 0.0
    if any(word in text for word in ("左右", "横", "side to side")):
        x = 0.18
    elif any(word in text for word in ("上下", "縦", "up and down")):
        y = 0.18
    elif any(word in text for word in ("前後", "forward and back")):
        z = 0.18
    elif any(word in text for word in ("上", "up")):
        y = 0.22
    elif any(word in text for word in ("下", "down")):
        y = -0.22
    elif any(word in text for word in ("前", "forward")):
        z = 0.22
    elif any(word in text for word in ("後ろ", "back")):
        z = -0.22
    else:
        x = 0.16
    return BodyMotionVector(x, y, z)


def _timing(text: str) -> BodyMotionTiming:
    duration_match = _DURATION_PATTERN.search(text)
    repetition_match = _REPETITION_PATTERN.search(text)
    duration = float(duration_match.group("value")) if duration_match else 1.2
    repetitions = int(repetition_match.group("value")) if repetition_match else 1
    hold_final = any(word in text for word in ("そのまま", "止め", "キープ", "保持", "hold"))
    return BodyMotionTiming(
        duration_seconds=max(0.05, min(120.0, duration)),
        repetitions=max(1, min(64, repetitions)),
        hold_final=hold_final,
    )


def _axis(text: str) -> str:
    if any(word in text for word in ("前後軸", "x軸", "x-axis")):
        return "x"
    if any(word in text for word in ("上下軸", "y軸", "y-axis")):
        return "y"
    return "z"


def _direction_sign(text: str) -> int:
    return -1 if any(word in text for word in ("逆", "反時計", "counterclockwise")) else 1


def _radius(text: str) -> float:
    match = re.search(r"(?:半径|radius)\s*[=:]?\s*(\d+(?:\.\d+)?)", text)
    return max(0.02, min(4.0, float(match.group(1)))) if match else 0.28


def _rotation_amount(text: str) -> float:
    degree_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:度|degrees?)", text)
    if degree_match:
        return math.radians(float(degree_match.group(1)))
    radian_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:rad|radians?)", text)
    if radian_match:
        return float(radian_match.group(1))
    return math.radians(35.0)


def _meaning_text(meaning: StructuredInputMeaning) -> str:
    parts = [meaning.source_text, meaning.primary_intent]
    parts.extend(meaning.information_provided)
    for collection in (meaning.entities, meaning.references):
        for item in collection:
            parts.extend(str(value) for value in item.values() if value is not None)
    return " ".join(part for part in parts if part)
