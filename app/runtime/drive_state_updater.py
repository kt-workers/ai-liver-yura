from __future__ import annotations

from datetime import datetime

from app.domain.desires import DesireState
from app.domain.drives import DriveState
from app.domain.emotions import AffectiveAppraisal, EmotionState
from app.domain.events import AgentEvent, AgentEventType
from app.utils.trace import TraceLogger

_ACKNOWLEDGEMENTS = frozenset(
    {
        "うん",
        "うんうん",
        "はい",
        "そう",
        "そうだね",
        "そうなんだ",
        "なるほど",
        "ふむ",
        "ふむふむ",
        "へえ",
        "ほう",
        "いいね",
        "わかった",
        "了解",
        "ok",
        "okay",
        "yes",
    }
)
_GREETINGS = frozenset(
    {
        "こんにちは",
        "こんばんは",
        "おはよう",
        "おはようございます",
        "やあ",
        "どうも",
        "hello",
        "hi",
    }
)


class DriveStateUpdater:
    """Emotion・Desire・疲労からDriveStateを導出するRuntime部品。"""

    def __init__(self, trace_logger: TraceLogger | None = None) -> None:
        self._trace_logger = trace_logger or TraceLogger()

    def derive_from_affect(
        self,
        drive: DriveState,
        event: AgentEvent,
        *,
        affective_appraisal: AffectiveAppraisal,
        emotion: EmotionState,
        desire: DesireState,
        activity_active: bool,
    ) -> DriveState:
        """人格的内容を決めず、現在の活性・準備状態だけを導出する。"""

        dimensions = affective_appraisal.dimensions
        desire_curiosity_projection = self._clamp(
            desire.curiosity.effective_level + dimensions.novelty * 0.18
        )
        drive_inertia_ratio = (
            1.0 if event.event_type == AgentEventType.CURIOSITY_PEAK else 0.96
        )
        drive_curiosity_inertia = drive.curiosity * drive_inertia_ratio
        curiosity_compatibility = max(
            desire_curiosity_projection,
            drive_curiosity_inertia,
        )
        curiosity_source = (
            "previous_drive_inertia"
            if drive_curiosity_inertia > desire_curiosity_projection
            else "desire_curiosity_compatibility"
        )
        engagement_target = self._clamp(
            0.25
            + emotion.arousal * 0.22
            + dimensions.social_relevance * 0.25
            + max(0.0, dimensions.approach) * 0.14
            + dimensions.relationship_significance * 0.12
            - dimensions.tension * 0.18,
        )
        boredom_target = self._clamp(
            0.45
            - emotion.arousal * 0.30
            - dimensions.novelty * 0.28
            - dimensions.social_relevance * 0.42
            - engagement_target * 0.20
            + (0.06 if not activity_active else 0.0),
        )
        energy_delta = self._event_energy_delta(event.event_type)
        if activity_active:
            energy_delta -= 0.004
        input_stimulus_scale, input_kind = self._causal_input_observation(event)
        updated = DriveState(
            curiosity=curiosity_compatibility,
            engagement=self._move_toward(drive.engagement, engagement_target, 0.30),
            boredom=self._move_toward(drive.boredom, boredom_target, 0.24),
            energy=drive.energy + energy_delta,
        )
        self._trace_logger.info(
            "drive_state_updater:causal_derivation",
            source_event_id=event.event_id,
            event_type=event.event_type.value,
            affective_cause=affective_appraisal.cause_category,
            input_kind=input_kind,
            stimulus_scale=input_stimulus_scale,
            input_classification_observation_only=input_kind is not None,
            curiosity_source=curiosity_source,
            desire_curiosity_projection=desire_curiosity_projection,
            drive_curiosity_inertia=drive_curiosity_inertia,
            activity_active=activity_active,
            engagement_target=engagement_target,
            boredom_target=boredom_target,
            before_curiosity=drive.curiosity,
            after_curiosity=updated.curiosity,
            before_engagement=drive.engagement,
            after_engagement=updated.engagement,
            before_boredom=drive.boredom,
            after_boredom=updated.boredom,
            before_energy=drive.energy,
            after_energy=updated.energy,
        )
        return updated

    def derive_by_elapsed_time(
        self,
        drive: DriveState,
        *,
        emotion: EmotionState,
        desire: DesireState,
        elapsed_seconds: float,
        activity_active: bool,
    ) -> DriveState:
        """時間経過による疲労・回復と、現在Emotionへの追従を計算する。"""

        elapsed_minutes = max(0.0, elapsed_seconds) / 60.0
        if elapsed_minutes == 0.0:
            return drive
        idle_exploration_pressure = (
            0.0 if activity_active else min(0.40, 0.06 * elapsed_minutes)
        )
        curiosity_target = self._clamp(
            desire.curiosity.effective_level + idle_exploration_pressure
        )
        engagement_target = self._clamp(
            0.20
            + emotion.arousal * 0.28
            + max(0.0, emotion.valence) * 0.12
            - emotion.reactive.emotional_pressure * 0.18
            - emotion.reactive.discomfort * 0.14,
        )
        boredom_target = self._clamp(
            0.68
            - emotion.arousal * 0.34
            - engagement_target * 0.24
            - curiosity_target * 0.16,
        )
        follow_ratio = min(1.0, 0.10 * elapsed_minutes)
        if activity_active:
            energy = drive.energy - 0.012 * elapsed_minutes
        elif emotion.arousal < 0.45:
            energy = drive.energy + (0.72 - drive.energy) * min(
                1.0,
                0.06 * elapsed_minutes,
            )
        else:
            energy = drive.energy - 0.003 * elapsed_minutes
        updated = DriveState(
            curiosity=self._move_toward(
                drive.curiosity,
                curiosity_target,
                follow_ratio,
            ),
            engagement=self._move_toward(
                drive.engagement,
                engagement_target,
                follow_ratio,
            ),
            boredom=self._move_toward(
                drive.boredom,
                boredom_target,
                follow_ratio,
            ),
            energy=energy,
        )
        self._write_update_trace(
            "drive_state_updater:causal_elapsed_derivation",
            before_drive=drive,
            after_drive=updated,
            elapsed_seconds=elapsed_seconds,
            elapsed_minutes=elapsed_minutes,
            activity_active=activity_active,
            curiosity_source="desire_curiosity_plus_idle_exploration_pressure",
            idle_exploration_pressure=idle_exploration_pressure,
        )
        return updated

    def update_by_event(self, drive: DriveState, event: AgentEvent) -> DriveState:
        """旧Event直接更新。移行期間の互換APIとしてのみ維持する。"""

        if event.event_type in (
            AgentEventType.USER_TEXT,
            AgentEventType.YOUTUBE_COMMENT,
            AgentEventType.USER_SPEECH,
        ):
            input_text = self._event_text(event)
            stimulus_scale, input_kind = self._input_stimulus(input_text)
            updated_drive = self._apply_user_input(drive, stimulus_scale)
            self._write_update_trace(
                "drive_state_updater:update_by_event:user_input",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
                input_kind=input_kind,
                stimulus_scale=stimulus_scale,
                compatibility_path=True,
            )
            return updated_drive

        if event.event_type == AgentEventType.USER_INTERACTION:
            updated_drive = self._apply_user_interaction(drive)
            self._write_update_trace(
                "drive_state_updater:update_by_event:user_interaction",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
                compatibility_path=True,
            )
            return updated_drive

        if event.event_type in (
            AgentEventType.APP_STARTED,
            AgentEventType.STREAM_STARTED,
        ):
            updated_drive = self._apply_lifecycle_started(drive, event)
            self._write_update_trace(
                "drive_state_updater:update_by_event:lifecycle_started",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
                compatibility_path=True,
            )
            return updated_drive

        if event.event_type == AgentEventType.SPEECH_FINISHED:
            updated_drive = self._apply_speech_finished(drive)
            self._write_update_trace(
                "drive_state_updater:update_by_event:speech_finished",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
                compatibility_path=True,
            )
            return updated_drive

        if event.event_type == AgentEventType.ACTION_FAILED:
            updated_drive = self._apply_action_failed(drive)
            self._write_update_trace(
                "drive_state_updater:update_by_event:action_failed",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
                compatibility_path=True,
            )
            return updated_drive

        self._trace_logger.write(
            "drive_state_updater:update_by_event:no_change",
            event_type=event.event_type.value,
            curiosity=drive.curiosity,
            engagement=drive.engagement,
            boredom=drive.boredom,
            energy=drive.energy,
            compatibility_path=True,
        )
        return drive

    def update_by_elapsed_time(
        self,
        drive: DriveState,
        elapsed_seconds: float,
    ) -> DriveState:
        """旧時間更新。移行期間の互換APIとしてのみ維持する。"""

        elapsed_minutes = max(0.0, elapsed_seconds) / 60.0

        updated_drive = DriveState(
            curiosity=self._increase_toward_one(
                drive.curiosity,
                0.06 * elapsed_minutes,
            ),
            engagement=drive.engagement - (0.01 * elapsed_minutes),
            boredom=drive.boredom + (0.14 * elapsed_minutes),
            energy=drive.energy - (0.005 * elapsed_minutes),
        )
        self._write_update_trace(
            "drive_state_updater:update_by_elapsed_time",
            before_drive=drive,
            after_drive=updated_drive,
            elapsed_seconds=elapsed_seconds,
            elapsed_minutes=elapsed_minutes,
            compatibility_path=True,
        )
        return updated_drive

    def update_by_timestamps(
        self,
        drive: DriveState,
        previous_time: datetime,
        current_time: datetime,
    ) -> DriveState:
        elapsed_seconds = (current_time - previous_time).total_seconds()
        return self.update_by_elapsed_time(drive, elapsed_seconds)

    def _apply_lifecycle_started(
        self, drive: DriveState, event: AgentEvent
    ) -> DriveState:
        if event.event_type == AgentEventType.STREAM_STARTED:
            return DriveState(
                curiosity=drive.curiosity + 0.08,
                engagement=drive.engagement + 0.18,
                boredom=drive.boredom + 0.02,
                energy=drive.energy + 0.04,
            )
        return drive

    def _apply_user_input(
        self,
        drive: DriveState,
        stimulus_scale: float,
    ) -> DriveState:
        return DriveState(
            curiosity=self._increase_toward_one(
                drive.curiosity,
                0.18 * stimulus_scale,
            ),
            engagement=self._increase_toward_one(
                drive.engagement,
                0.32 * stimulus_scale,
            ),
            boredom=drive.boredom - (0.3 * stimulus_scale),
            energy=drive.energy - (0.03 * stimulus_scale),
        )

    def _apply_user_interaction(self, drive: DriveState) -> DriveState:
        return DriveState(
            curiosity=drive.curiosity + 0.03,
            engagement=drive.engagement + 0.08,
            boredom=drive.boredom - 0.08,
            energy=drive.energy - 0.01,
        )

    def _apply_speech_finished(self, drive: DriveState) -> DriveState:
        return DriveState(
            curiosity=drive.curiosity - 0.015,
            engagement=drive.engagement + 0.02,
            boredom=drive.boredom - 0.02,
            energy=drive.energy - 0.015,
        )

    def _apply_action_failed(self, drive: DriveState) -> DriveState:
        return DriveState(
            curiosity=drive.curiosity + 0.05,
            engagement=drive.engagement - 0.1,
            boredom=drive.boredom + 0.05,
            energy=drive.energy - 0.05,
        )

    @staticmethod
    def _event_energy_delta(event_type: AgentEventType) -> float:
        return {
            AgentEventType.STREAM_STARTED: 0.03,
            AgentEventType.SPEECH_FINISHED: -0.015,
            AgentEventType.ACTION_FAILED: -0.05,
            AgentEventType.USER_INTERACTION: -0.008,
            AgentEventType.USER_TEXT: -0.008,
            AgentEventType.USER_SPEECH: -0.010,
            AgentEventType.YOUTUBE_COMMENT: -0.008,
        }.get(event_type, 0.0)

    @classmethod
    def _causal_input_observation(
        cls,
        event: AgentEvent,
    ) -> tuple[float | None, str | None]:
        if event.event_type not in {
            AgentEventType.USER_TEXT,
            AgentEventType.YOUTUBE_COMMENT,
            AgentEventType.USER_SPEECH,
        }:
            return None, None
        return cls._input_stimulus(cls._event_text(event))

    @staticmethod
    def _event_text(event: AgentEvent) -> str:
        for key in ("text", "comment", "transcript", "utterance"):
            value = event.payload.get(key)
            if isinstance(value, str):
                return value
        return ""

    @classmethod
    def _input_stimulus(cls, text: str) -> tuple[float, str]:
        normalized = cls._normalize_input_text(text)
        if normalized in _ACKNOWLEDGEMENTS:
            return 0.25, "acknowledgement"
        if normalized in _GREETINGS:
            return 0.6, "greeting"
        if not normalized:
            return 0.5, "unknown"
        return 1.0, "substantive"

    @staticmethod
    def _normalize_input_text(text: str) -> str:
        return text.strip().lower().strip("。.!！?？、, ")

    @staticmethod
    def _increase_toward_one(value: float, rate: float) -> float:
        normalized_rate = max(0.0, min(1.0, rate))
        return value + ((1.0 - value) * normalized_rate)

    @staticmethod
    def _move_toward(current: float, target: float, ratio: float) -> float:
        bounded_ratio = max(0.0, min(1.0, ratio))
        return current + (target - current) * bounded_ratio

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

    def _write_update_trace(
        self,
        label: str,
        before_drive: DriveState,
        after_drive: DriveState,
        **values: object,
    ) -> None:
        self._trace_logger.debug(
            label,
            **values,
            before_curiosity=before_drive.curiosity,
            before_engagement=before_drive.engagement,
            before_boredom=before_drive.boredom,
            before_energy=before_drive.energy,
            after_curiosity=after_drive.curiosity,
            after_engagement=after_drive.engagement,
            after_boredom=after_drive.boredom,
            after_energy=after_drive.energy,
        )
