from __future__ import annotations

from app.domain.activities import Activity
from app.domain.body import (
    BodyAttentionBehavior,
    BodyAttentionIntent,
)


class BodySpatialCommandResolver:
    """構造化された方向指示をBodyの注意方針へ変換する。"""

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

    def resolve(self, activity: Activity) -> BodyAttentionIntent | None:
        meaning = self._structured_input_meaning(activity)
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

        target = meaning.get("target")
        if not isinstance(target, dict):
            return None
        target_type = str(target.get("type", "")).strip().lower()
        target_id = str(target.get("id", "")).strip().lower()
        if target_type not in self._SUPPORTED_TYPES:
            return None
        if target_id not in self._SUPPORTED_DIRECTIONS:
            return None

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
