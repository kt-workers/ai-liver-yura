from __future__ import annotations

from collections.abc import Mapping

from app.domain.activities import Activity, ActivityType
from app.domain.body import BodyActivityContext, BodyPostureTendency


class BodyActivityContextBuilder:
    """Activityを毎フレーム命令ではない継続的な身体文脈へ変換する。"""

    _DEFAULTS: dict[
        ActivityType,
        tuple[str | None, float, BodyPostureTendency, float, float],
    ] = {
        ActivityType.CONVERSATION_WITH_USER: (
            "conversation_partner",
            0.72,
            BodyPostureTendency.OPEN,
            0.38,
            0.25,
        ),
        ActivityType.DIRECTED_TALK: (
            "audience",
            0.68,
            BodyPostureTendency.OPEN,
            0.46,
            0.32,
        ),
        ActivityType.LISTENING_MODE: (
            "conversation_partner",
            0.82,
            BodyPostureTendency.FORWARD,
            0.24,
            0.18,
        ),
        ActivityType.STIMULUS_REACTION: (
            "stimulus",
            0.78,
            BodyPostureTendency.NEUTRAL,
            0.58,
            0.42,
        ),
        ActivityType.IDLE_OBSERVATION: (
            None,
            0.25,
            BodyPostureTendency.NEUTRAL,
            0.22,
            0.88,
        ),
        ActivityType.BODY_EXPRESSION_LOOP: (
            None,
            0.35,
            BodyPostureTendency.NEUTRAL,
            0.32,
            0.72,
        ),
    }

    def build(self, activity: Activity) -> BodyActivityContext:
        defaults = self._DEFAULTS.get(
            activity.activity_type,
            (
                None,
                0.5,
                BodyPostureTendency.NEUTRAL,
                0.35,
                0.5,
            ),
        )
        raw = activity.context.get("body_context", {})
        overrides: Mapping[str, object] = raw if isinstance(raw, Mapping) else {}

        attention_target = self._optional_name(
            overrides.get("attention_target"),
            defaults[0],
        )
        posture_tendency = self._posture(
            overrides.get("posture_tendency"),
            defaults[2],
        )
        return BodyActivityContext(
            source_activity_id=activity.activity_id,
            attention_target=attention_target,
            engagement=self._unit(overrides.get("engagement"), defaults[1]),
            posture_tendency=posture_tendency,
            movement_energy=self._unit(
                overrides.get("movement_energy"),
                defaults[3],
            ),
            gaze_freedom=self._unit(
                overrides.get("gaze_freedom"),
                defaults[4],
            ),
        )

    @staticmethod
    def _unit(value: object, default: float) -> float:
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0.0 <= float(value) <= 1.0
        ):
            return float(value)
        return default

    @staticmethod
    def _optional_name(value: object, default: str | None) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    @staticmethod
    def _posture(
        value: object,
        default: BodyPostureTendency,
    ) -> BodyPostureTendency:
        if isinstance(value, BodyPostureTendency):
            return value
        if isinstance(value, str):
            try:
                return BodyPostureTendency(value.strip())
            except ValueError:
                pass
        return default
