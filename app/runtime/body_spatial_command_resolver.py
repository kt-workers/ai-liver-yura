from __future__ import annotations

import re

from app.domain.activities import Activity
from app.domain.body import (
    BodyAttentionBehavior,
    BodyAttentionIntent,
)


class BodySpatialCommandResolver:
    """構造化された方向・身体操作指示をBody要求へ変換する。

    StructuredInputMeaningの`target`は主対象を一つだけ持つため、複合身体命令では
    source text・entities・information_providedも合わせて読み、Body向けには複数の
    正規化Actionを返す。
    """

    _SUPPORTED_TYPES = {
        "gaze_direction",
        "orientation_direction",
        "spatial_direction",
        "direction",
    }
    _SUPPORTED_DIRECTIONS = {
        "left",
        "right",
        "up",
        "down",
        "up_left",
        "up_right",
        "down_left",
        "down_right",
        "center",
    }
    _BODY_ACTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
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
        (
            "right_hand_raise",
            ("右手を挙げ", "右手を上げ", "右腕を挙げ", "右腕を上げ"),
        ),
        (
            "left_hand_raise",
            ("左手を挙げ", "左手を上げ", "左腕を挙げ", "左腕を上げ"),
        ),
        (
            "both_hands_raise",
            ("両手を挙げ", "両手を上げ", "両腕を挙げ", "両腕を上げ"),
        ),
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
    _SUPPORTED_BODY_ACTIONS = frozenset(
        action for action, _patterns in _BODY_ACTION_PATTERNS
    )
    _JAPANESE_DIRECTION_COMMAND = re.compile(
        r"(?P<direction>右上|左上|右下|左下|正面|中央|右|左|上|下)"
        r"(?:の方)?(?:を)?"
        r"(?P<marker>見て|見たまま|見ながら|見続け|向いて|向いたまま|向きながら|向けて|振り向いて)"
    )
    _REPEAT_MARKERS = (
        "もう一回",
        "もう1回",
        "もう一度",
        "同じ動きをもう一回",
        "さっきの動きをもう一回",
        "repeat_previous_action",
    )
    _COUNT_PATTERN = re.compile(r"(?P<count>[2-8２-８二三四五六七八])\s*回")
    _COUNT_VALUES = {
        "2": 2,
        "3": 3,
        "4": 4,
        "5": 5,
        "6": 6,
        "7": 7,
        "8": 8,
        "２": 2,
        "３": 3,
        "４": 4,
        "５": 5,
        "６": 6,
        "７": 7,
        "８": 8,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
    }
    _DIRECTION_IDS = {
        "右上": "up_right",
        "左上": "up_left",
        "右下": "down_right",
        "左下": "down_left",
        "正面": "center",
        "中央": "center",
        "右": "right",
        "左": "left",
        "上": "up",
        "下": "down",
    }

    def resolve(self, activity: Activity) -> BodyAttentionIntent | None:
        meaning = self._eligible_meaning(activity)
        if meaning is None:
            return None

        target_type = ""
        target_id = ""
        target = meaning.get("target")
        if isinstance(target, dict):
            candidate_type = str(target.get("type", "")).strip().lower()
            candidate_id = str(target.get("id", "")).strip().lower()
            if (
                candidate_type in self._SUPPORTED_TYPES
                and candidate_id in self._SUPPORTED_DIRECTIONS
            ):
                target_type = candidate_type
                target_id = candidate_id

        if not target_id:
            command = self._direction_command(self._meaning_text(activity, meaning))
            if command is None:
                return None
            target_type, target_id = command

        confidence = meaning.get("confidence", 1.0)
        engagement = (
            float(confidence)
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
            else 1.0
        )
        engagement = min(1.0, max(0.6, engagement))

        if target_type == "orientation_direction":
            return BodyAttentionIntent(
                target=target_id,
                behavior=BodyAttentionBehavior.MAINTAIN,
                engagement=engagement,
                avoidance=0.0,
                eye_follow=1.0,
                head_follow=1.0,
                body_follow=0.78,
            )

        return BodyAttentionIntent(
            target=target_id,
            behavior=BodyAttentionBehavior.MAINTAIN,
            engagement=engagement,
            avoidance=0.0,
            eye_follow=1.0,
            head_follow=0.72,
            body_follow=0.12,
        )

    def resolve_body_actions(self, activity: Activity) -> tuple[str, ...]:
        meaning = self._eligible_meaning(activity)
        if meaning is None:
            return ()

        text = self._meaning_text(activity, meaning)
        matches: list[tuple[int, int, str]] = []
        for order, (action, patterns) in enumerate(self._BODY_ACTION_PATTERNS):
            positions = [text.find(pattern) for pattern in patterns if pattern in text]
            if positions:
                matches.append((min(positions), order, action))

        target = meaning.get("target")
        target_action = ""
        if isinstance(target, dict) and str(target.get("type", "")).strip().lower() == "avatar_body_action":
            candidate = str(target.get("id", "")).strip().lower()
            if candidate in self._SUPPORTED_BODY_ACTIONS:
                target_action = candidate
        if target_action and not any(action == target_action for _, _, action in matches):
            matches.append((-1, -1, target_action))

        matches.sort(key=lambda item: (item[0], item[1]))
        actions = tuple(action for _, _, action in matches)
        repetition = self._explicit_repetition_count(text)
        if len(actions) == 1 and repetition > 1:
            return actions * repetition
        return actions

    def is_repeat_request(self, activity: Activity) -> bool:
        meaning = self._eligible_meaning(activity)
        if meaning is None:
            return False
        primary_intent = str(meaning.get("primary_intent", "")).strip().lower()
        text = self._meaning_text(activity, meaning)
        return primary_intent == "repeat_previous_action" or any(
            marker in text for marker in self._REPEAT_MARKERS
        )

    @classmethod
    def supported_body_actions(cls) -> frozenset[str]:
        return cls._SUPPORTED_BODY_ACTIONS

    @classmethod
    def _direction_command(cls, text: str) -> tuple[str, str] | None:
        match = cls._JAPANESE_DIRECTION_COMMAND.search(text)
        if match is None:
            return None
        direction = cls._DIRECTION_IDS[match.group("direction")]
        marker = match.group("marker")
        target_type = "orientation_direction" if "向" in marker or "振り向" in marker else "gaze_direction"
        return target_type, direction

    @classmethod
    def _explicit_repetition_count(cls, text: str) -> int:
        match = cls._COUNT_PATTERN.search(text)
        if match is None:
            return 1
        return cls._COUNT_VALUES.get(match.group("count"), 1)

    @classmethod
    def _eligible_meaning(cls, activity: Activity) -> dict[str, object] | None:
        meaning = cls._structured_input_meaning(activity)
        if meaning is None:
            return None
        if str(meaning.get("expected_response", "")).strip().lower() != "action":
            return None
        if str(meaning.get("input_speech_act", "")).strip().lower() not in {
            "command",
            "request",
            "proposal",
        }:
            return None
        return meaning

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
            meaning = cls._find_meaning(candidate)
            if meaning is not None:
                return meaning
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

    @classmethod
    def _meaning_text(
        cls,
        activity: Activity,
        meaning: dict[str, object],
    ) -> str:
        parts: list[str] = []
        for key in ("source_text", "primary_intent"):
            value = meaning.get(key)
            if isinstance(value, str):
                parts.append(value)
        information = meaning.get("information_provided")
        if isinstance(information, list):
            parts.extend(str(value) for value in information if value is not None)
        for key in ("entities", "references"):
            values = meaning.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict):
                    parts.extend(str(value) for value in item.values() if value is not None)

        for container in (activity.context, activity.context.get("event_payload")):
            if not isinstance(container, dict):
                continue
            for key in ("text", "user_input", "input_text", "raw_text", "source_text"):
                value = container.get(key)
                if isinstance(value, str):
                    parts.append(value)
        return " ".join(part for part in parts if part).casefold()
