from __future__ import annotations

from datetime import datetime

from app.domain.drives import DriveState
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
    """Event と時間経過から DriveState を更新する Runtime 部品。"""

    def __init__(self, trace_logger: TraceLogger | None = None) -> None:
        self._trace_logger = trace_logger or TraceLogger()

    def update_by_event(self, drive: DriveState, event: AgentEvent) -> DriveState:
        """AgentEvent の種類に応じて内的動機を更新する。"""

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
            )
            return updated_drive

        if event.event_type == AgentEventType.USER_INTERACTION:
            stimulus_scale, interaction_kind, contact_phase = (
                self._interaction_stimulus(event)
            )
            updated_drive = self._apply_user_interaction(drive, stimulus_scale)
            self._write_update_trace(
                "drive_state_updater:update_by_event:user_interaction",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
                interaction_kind=interaction_kind,
                contact_phase=contact_phase,
                stimulus_scale=stimulus_scale,
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
            )
            return updated_drive

        if event.event_type == AgentEventType.SPEECH_FINISHED:
            updated_drive = self._apply_speech_finished(drive)
            self._write_update_trace(
                "drive_state_updater:update_by_event:speech_finished",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
            )
            return updated_drive

        if event.event_type == AgentEventType.ACTION_FAILED:
            updated_drive = self._apply_action_failed(drive)
            self._write_update_trace(
                "drive_state_updater:update_by_event:action_failed",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
            )
            return updated_drive

        self._trace_logger.write(
            "drive_state_updater:update_by_event:no_change",
            event_type=event.event_type.value,
            curiosity=drive.curiosity,
            engagement=drive.engagement,
            boredom=drive.boredom,
            energy=drive.energy,
        )
        return drive

    def update_by_elapsed_time(
        self,
        drive: DriveState,
        elapsed_seconds: float,
    ) -> DriveState:
        """時間経過に応じて内的動機を更新する。"""

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
        )
        return updated_drive

    def update_by_timestamps(
        self,
        drive: DriveState,
        previous_time: datetime,
        current_time: datetime,
    ) -> DriveState:
        """前回更新時刻と現在時刻の差分から内的動機を更新する。"""

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

    def _apply_user_interaction(
        self,
        drive: DriveState,
        stimulus_scale: float,
    ) -> DriveState:
        return DriveState(
            curiosity=drive.curiosity + (0.03 * stimulus_scale),
            engagement=drive.engagement + (0.08 * stimulus_scale),
            boredom=drive.boredom - (0.08 * stimulus_scale),
            energy=drive.energy - (0.01 * stimulus_scale),
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
    def _interaction_stimulus(
        event: AgentEvent,
    ) -> tuple[float, str, str | None]:
        stimulus_value = event.payload.get("stimulus_kind")
        stimulus_kind = (
            stimulus_value.strip().lower()
            if isinstance(stimulus_value, str) and stimulus_value.strip()
            else "unknown"
        )
        phase_value = event.payload.get("contact_phase") or event.payload.get(
            "gesture_phase"
        )
        contact_phase = (
            phase_value.strip().lower()
            if isinstance(phase_value, str) and phase_value.strip()
            else None
        )
        continuous_contact = (
            event.payload.get("continuous_contact") is True
            or contact_phase in {"start", "update", "end"}
        )
        if continuous_contact:
            if contact_phase == "start":
                return 0.35, f"{stimulus_kind}_start", contact_phase
            if contact_phase == "end":
                return 0.15, f"{stimulus_kind}_end", contact_phase
            if contact_phase == "update":
                return 0.0, f"{stimulus_kind}_update", contact_phase
            return 0.25, f"{stimulus_kind}_continuous", contact_phase
        if stimulus_kind in {"tap", "double_tap", "long_press", "drag"}:
            return 1.0, stimulus_kind, contact_phase
        return 0.5, stimulus_kind, contact_phase

    @staticmethod
    def _normalize_input_text(text: str) -> str:
        return text.strip().lower().strip("。.!！?？、, ")

    @staticmethod
    def _increase_toward_one(value: float, rate: float) -> float:
        normalized_rate = max(0.0, min(1.0, rate))
        return value + ((1.0 - value) * normalized_rate)

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
