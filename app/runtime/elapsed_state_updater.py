from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.desires import DesireState
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState
from app.runtime.agent_state import AgentState
from app.runtime.desire_state_updater import DesireStateUpdater
from app.runtime.drive_state_updater import DriveStateUpdater
from app.runtime.emotion_state_updater import EmotionStateUpdater


@dataclass(frozen=True, slots=True)
class ElapsedStateUpdateResult:
    state: AgentState
    drive_elapsed_seconds: float
    desire_elapsed_seconds: float
    emotion_elapsed_seconds: float
    before_drive: DriveState
    after_drive: DriveState
    before_desire: DesireState
    after_desire: DesireState
    before_emotion: EmotionState
    after_emotion: EmotionState

    @property
    def desire_changed(self) -> bool:
        return self.before_desire != self.after_desire

    @property
    def emotion_changed(self) -> bool:
        return self.before_emotion != self.after_emotion


class ElapsedStateUpdater:
    """経過時間に基づくDrive・Desire・Emotion更新と基準時刻を管理する。"""

    def __init__(
        self,
        *,
        initial_time: datetime,
        drive_state_updater: DriveStateUpdater | None = None,
        desire_state_updater: DesireStateUpdater | None = None,
        emotion_state_updater: EmotionStateUpdater | None = None,
    ) -> None:
        self._drive_state_updater = drive_state_updater or DriveStateUpdater()
        self._desire_state_updater = desire_state_updater or DesireStateUpdater()
        self._emotion_state_updater = emotion_state_updater or EmotionStateUpdater()
        self._last_drive_updated_at = initial_time
        self._last_desire_updated_at = initial_time
        self._last_emotion_updated_at = initial_time

    @property
    def last_drive_updated_at(self) -> datetime:
        return self._last_drive_updated_at

    @property
    def last_desire_updated_at(self) -> datetime:
        return self._last_desire_updated_at

    @property
    def last_emotion_updated_at(self) -> datetime:
        return self._last_emotion_updated_at

    def update(self, state: AgentState, *, now: datetime) -> ElapsedStateUpdateResult:
        before_drive = state.current_drive
        drive_elapsed_seconds = (now - self._last_drive_updated_at).total_seconds()
        after_drive = self._drive_state_updater.update_by_timestamps(
            before_drive,
            previous_time=self._last_drive_updated_at,
            current_time=now,
        )
        self._last_drive_updated_at = now

        before_desire = state.current_desire
        desire_elapsed_seconds = (now - self._last_desire_updated_at).total_seconds()
        after_desire = self._desire_state_updater.update_by_timestamps(
            before_desire,
            previous_time=self._last_desire_updated_at,
            current_time=now,
        )
        self._last_desire_updated_at = max(self._last_desire_updated_at, now)

        before_emotion = state.current_emotion
        emotion_elapsed_seconds = max(
            0.0,
            (now - self._last_emotion_updated_at).total_seconds(),
        )
        after_emotion = self._emotion_state_updater.decay(
            before_emotion,
            elapsed_seconds=emotion_elapsed_seconds,
        )
        self._last_emotion_updated_at = max(self._last_emotion_updated_at, now)

        updated_state = (
            state.with_drive(after_drive)
            .with_desire(after_desire)
            .with_emotion(after_emotion)
        )
        return ElapsedStateUpdateResult(
            state=updated_state,
            drive_elapsed_seconds=drive_elapsed_seconds,
            desire_elapsed_seconds=desire_elapsed_seconds,
            emotion_elapsed_seconds=emotion_elapsed_seconds,
            before_drive=before_drive,
            after_drive=after_drive,
            before_desire=before_desire,
            after_desire=after_desire,
            before_emotion=before_emotion,
            after_emotion=after_emotion,
        )

    def record_event(self, occurred_at: datetime) -> None:
        """Event反映済み状態を、以後の時間更新の基準時刻にする。"""

        self._last_desire_updated_at = max(
            self._last_desire_updated_at,
            occurred_at,
        )
        self._last_emotion_updated_at = max(
            self._last_emotion_updated_at,
            occurred_at,
        )
