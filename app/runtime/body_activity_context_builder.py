from __future__ import annotations

from collections.abc import Mapping

from app.domain.activities import Activity, ActivityType
from app.domain.body import (
    BodyActivityContext,
    BodyAffectContext,
    BodyPostureTendency,
)


class BodyActivityContextBuilder:
    """Activityと確定済みAgent状態を継続的な身体文脈へ変換する。

    毎フレームの角度や身体部位は決めない。Activityの方針に加えて、通常会話Eventへ
    格納済みのEmotion／Drive SnapshotをBody向けの有限値へ一方向投影する。
    """

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
        event_payload = self._mapping(activity.context.get("event_payload"))
        emotion = self._mapping(
            event_payload.get("emotion", activity.context.get("emotion"))
        )
        drive = self._mapping(
            event_payload.get("drive", activity.context.get("drive"))
        )

        drive_engagement = self._optional_unit(drive.get("engagement"))
        drive_energy = self._optional_unit(drive.get("energy"))
        drive_curiosity = self._optional_unit(drive.get("curiosity"))

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
            engagement=self._unit(
                overrides.get("engagement"),
                drive_engagement if drive_engagement is not None else defaults[1],
            ),
            posture_tendency=posture_tendency,
            movement_energy=self._unit(
                overrides.get("movement_energy"),
                drive_energy if drive_energy is not None else defaults[3],
            ),
            gaze_freedom=self._unit(
                overrides.get("gaze_freedom"),
                (
                    max(0.08, min(0.96, 0.18 + drive_curiosity * 0.72))
                    if drive_curiosity is not None
                    else defaults[4]
                ),
            ),
            affect=self._affect_context(emotion),
        )

    @classmethod
    def _affect_context(
        cls,
        emotion: Mapping[str, object],
    ) -> BodyAffectContext | None:
        if not emotion:
            return None
        reactive = cls._mapping(emotion.get("reactive"))
        values = {
            "valence": cls._signed(emotion.get("valence"), 0.0),
            "arousal": cls._unit(emotion.get("arousal"), 0.5),
            "joy": cls._unit(reactive.get("joy"), 0.0),
            "amusement": cls._unit(reactive.get("amusement"), 0.0),
            "anger": cls._unit(reactive.get("anger"), 0.0),
            "sadness": cls._unit(reactive.get("sadness"), 0.0),
            "fear": cls._unit(reactive.get("fear"), 0.0),
            "surprise": cls._unit(reactive.get("surprise"), 0.0),
            "discomfort": cls._unit(reactive.get("discomfort"), 0.0),
            "emotional_pressure": cls._unit(
                reactive.get("emotional_pressure"),
                0.0,
            ),
        }
        return BodyAffectContext(**values)

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _optional_unit(value: object) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(1.0, float(value)))
        return None

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
    def _signed(value: object, default: float) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(-1.0, min(1.0, float(value)))
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
