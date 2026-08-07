from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.awakening import (
    AwakeningCapabilities,
    AwakeningContext,
    AwakeningDesireSnapshot,
    AwakeningDriveSnapshot,
    AwakeningEmotionSnapshot,
    AwakeningInnerStateSnapshot,
    AwakeningSnapshotLoadStatus,
    AwakeningStartupKind,
)
from app.domain.awakening_state import AwakeningAppraisal


@dataclass(frozen=True, slots=True)
class AwakeningContextParser:
    """APP_STARTEDの有限Payloadを型付きAwakeningContextへ戻す。"""

    def parse(self, value: object) -> AwakeningContext | None:
        if not isinstance(value, dict):
            return None
        try:
            startup_kind = AwakeningStartupKind(str(value["startup_kind"]))
            started_at = self._datetime(value["started_at"])
            persistence_status = AwakeningSnapshotLoadStatus(
                str(value["persistence_status"])
            )
            capabilities = self._capabilities(value["capabilities"])
            previous_shutdown_at = self._optional_datetime(
                value.get("previous_shutdown_at")
            )
            downtime = self._optional_number(value.get("downtime_seconds"))
            previous = self._inner_state(value.get("previous_inner_state"))
            reason = str(value.get("persistence_reason") or "")
            return AwakeningContext(
                startup_kind=startup_kind,
                started_at=started_at,
                capabilities=capabilities,
                persistence_status=persistence_status,
                previous_shutdown_at=previous_shutdown_at,
                downtime_seconds=downtime,
                previous_inner_state=previous,
                persistence_reason=reason,
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _mapping(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise TypeError("expected object")
        return {str(key): item for key, item in value.items()}

    @classmethod
    def _capabilities(cls, value: object) -> AwakeningCapabilities:
        payload = cls._mapping(value)
        return AwakeningCapabilities(
            body_available=bool(payload["body_available"]),
            tts_available=bool(payload["tts_available"]),
            conversation_output_available=bool(
                payload["conversation_output_available"]
            ),
        )

    @classmethod
    def _inner_state(cls, value: object) -> AwakeningInnerStateSnapshot | None:
        if value is None:
            return None
        payload = cls._mapping(value)
        emotion = cls._mapping(payload["emotion"])
        reactive = cls._mapping(emotion.get("reactive", {}))
        drive = cls._mapping(payload["drive"])
        desire = cls._mapping(payload["desire"])
        return AwakeningInnerStateSnapshot(
            emotion=AwakeningEmotionSnapshot(
                mood=str(emotion["mood"]),
                arousal=cls._number(emotion["arousal"]),
                valence=cls._number(emotion["valence"]),
                talkativeness=cls._number(emotion["talkativeness"]),
                joy=cls._number(reactive.get("joy", 0.0)),
                amusement=cls._number(reactive.get("amusement", 0.0)),
                anger=cls._number(reactive.get("anger", 0.0)),
                sadness=cls._number(reactive.get("sadness", 0.0)),
                fear=cls._number(reactive.get("fear", 0.0)),
                surprise=cls._number(reactive.get("surprise", 0.0)),
                discomfort=cls._number(reactive.get("discomfort", 0.0)),
                emotional_pressure=cls._number(
                    reactive.get("emotional_pressure", 0.0)
                ),
            ),
            drive=AwakeningDriveSnapshot(
                curiosity=cls._number(drive["curiosity"]),
                engagement=cls._number(drive["engagement"]),
                boredom=cls._number(drive["boredom"]),
                energy=cls._number(drive["energy"]),
            ),
            desire=AwakeningDesireSnapshot(
                connection=cls._number(desire["connection"]),
                curiosity=cls._number(desire["curiosity"]),
                expression=cls._number(desire["expression"]),
                recognition=cls._number(desire["recognition"]),
                autonomy=cls._number(desire["autonomy"]),
                security=cls._number(desire["security"]),
                achievement=cls._number(desire["achievement"]),
            ),
        )

    @staticmethod
    def _datetime(value: object) -> datetime:
        if not isinstance(value, str):
            raise TypeError("expected datetime string")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return parsed

    @classmethod
    def _optional_datetime(cls, value: object) -> datetime | None:
        return None if value is None else cls._datetime(value)

    @staticmethod
    def _number(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("expected number")
        return float(value)

    @classmethod
    def _optional_number(cls, value: object) -> float | None:
        return None if value is None else cls._number(value)


class AwakeningAppraiser:
    """起動事実を、表現非依存の覚醒意味へ決定論的に評価する。"""

    def appraise(self, context: AwakeningContext) -> AwakeningAppraisal:
        if not isinstance(context, AwakeningContext):
            raise TypeError("context must be AwakeningContext")

        previous = context.previous_inner_state
        downtime_hours = max(0.0, (context.downtime_seconds or 0.0) / 3600.0)
        if previous is None:
            prior_energy = 0.5
            prior_arousal = 0.5
            prior_talk = 0.5
            prior_curiosity = 0.5
            prior_engagement = 0.5
            prior_connection = 0.45
            prior_expression = 0.40
            prior_security = 0.35
            residual = 0.0
        else:
            prior_energy = previous.drive.energy
            prior_arousal = previous.emotion.arousal
            prior_talk = previous.emotion.talkativeness
            prior_curiosity = max(
                previous.drive.curiosity,
                previous.desire.curiosity,
            )
            prior_engagement = previous.drive.engagement
            prior_connection = previous.desire.connection
            prior_expression = previous.desire.expression
            prior_security = previous.desire.security
            residual = self._residual_weight(downtime_hours)

        restoration = self._restoration(
            context.startup_kind,
            downtime_hours=downtime_hours,
            prior_energy=prior_energy,
        )
        sleepiness = self._clamp(
            (1.0 - prior_energy) * 0.46
            + (1.0 - prior_arousal) * 0.28
            + (1.0 - restoration) * 0.26
        )
        activation = self._clamp(
            prior_energy * 0.38
            + prior_arousal * 0.28
            + restoration * 0.22
            + (1.0 - sleepiness) * 0.12
        )
        exploration = self._clamp(
            prior_curiosity * 0.72
            + activation * 0.20
            + (0.08 if context.startup_kind is AwakeningStartupKind.RESTART else 0.0)
        )
        social = self._clamp(
            prior_talk * 0.30
            + prior_engagement * 0.28
            + prior_connection * 0.22
            + prior_expression * 0.20
            - sleepiness * 0.22
        )
        capability_uncertainty = self._capability_uncertainty(context.capabilities)
        cold_uncertainty = (
            0.20 if context.startup_kind is AwakeningStartupKind.COLD_START else 0.0
        )
        persistence_uncertainty = (
            0.12
            if context.persistence_status
            in {
                AwakeningSnapshotLoadStatus.CORRUPT,
                AwakeningSnapshotLoadStatus.VERSION_MISMATCH,
                AwakeningSnapshotLoadStatus.IO_ERROR,
            }
            else 0.0
        )
        security = self._clamp(
            prior_security * 0.48
            + capability_uncertainty * 0.30
            + cold_uncertainty
            + persistence_uncertainty
        )
        orientation_base = {
            AwakeningStartupKind.COLD_START: 0.72,
            AwakeningStartupKind.RESTART: 0.52,
            AwakeningStartupKind.RESUME: 0.26,
        }[context.startup_kind]
        orientation = self._clamp(
            orientation_base
            + capability_uncertainty * 0.22
            + persistence_uncertainty * 0.18
            - activation * 0.08
        )
        readiness = self._clamp(
            activation * 0.32
            + (1.0 - sleepiness) * 0.24
            + (1.0 - security) * 0.18
            + (1.0 - orientation) * 0.18
            + restoration * 0.08
        )
        return AwakeningAppraisal(
            restoration=restoration,
            sleepiness=sleepiness,
            activation_urge=activation,
            exploration_urge=exploration,
            social_urge=social,
            security_need=security,
            orientation_need=orientation,
            residual_affect_weight=residual,
            readiness=readiness,
            reason=(
                f"{context.startup_kind.value}:downtime={round(context.downtime_seconds or 0.0)}s;"
                f"prior={'available' if previous is not None else 'missing'};"
                f"capability_uncertainty={capability_uncertainty:.3f}"
            ),
        )

    @staticmethod
    def _restoration(
        startup_kind: AwakeningStartupKind,
        *,
        downtime_hours: float,
        prior_energy: float,
    ) -> float:
        if startup_kind is AwakeningStartupKind.COLD_START:
            return 0.45
        time_rest = min(1.0, downtime_hours / 8.0)
        if startup_kind is AwakeningStartupKind.RESUME:
            time_rest *= 0.45
        recovery_room = 1.0 - prior_energy
        return AwakeningAppraiser._clamp(
            0.18 + time_rest * 0.62 + recovery_room * 0.20
        )

    @staticmethod
    def _residual_weight(downtime_hours: float) -> float:
        return AwakeningAppraiser._clamp(1.0 - downtime_hours / 6.0)

    @staticmethod
    def _capability_uncertainty(capabilities: AwakeningCapabilities) -> float:
        unavailable = sum(
            1
            for available in (
                capabilities.body_available,
                capabilities.tts_available,
                capabilities.conversation_output_available,
            )
            if not available
        )
        return unavailable / 3.0

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))


__all__ = ["AwakeningAppraiser", "AwakeningContextParser"]
