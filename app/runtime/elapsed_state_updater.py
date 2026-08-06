from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.desires import DesireState
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState
from app.domain.morals import MoralState
from app.runtime.agent_state import AgentState
from app.runtime.desire_state_updater import DesireStateUpdater
from app.runtime.drive_state_updater import DriveStateUpdater
from app.runtime.emotion_state_updater import EmotionStateUpdater
from app.runtime.moral_state_updater import MoralStateUpdater


@dataclass(frozen=True, slots=True)
class ElapsedStateUpdateResult:
    state: AgentState
    drive_elapsed_seconds: float
    desire_elapsed_seconds: float
    emotion_elapsed_seconds: float
    moral_elapsed_seconds: float
    before_drive: DriveState
    after_drive: DriveState
    before_desire: DesireState
    after_desire: DesireState
    before_emotion: EmotionState
    after_emotion: EmotionState
    before_moral: MoralState
    after_moral: MoralState

    @property
    def desire_changed(self) -> bool:
        return self.before_desire != self.after_desire

    @property
    def emotion_changed(self) -> bool:
        return self.before_emotion != self.after_emotion

    @property
    def moral_changed(self) -> bool:
        return self.before_moral != self.after_moral


class ElapsedStateUpdater:
    """経過時間に基づくEmotionと派生状態の更新を管理する。"""

    def __init__(
        self,
        *,
        initial_time: datetime,
        drive_state_updater: DriveStateUpdater | None = None,
        desire_state_updater: DesireStateUpdater | None = None,
        emotion_state_updater: EmotionStateUpdater | None = None,
        moral_state_updater: MoralStateUpdater | None = None,
    ) -> None:
        self._drive_state_updater = drive_state_updater or DriveStateUpdater()
        self._desire_state_updater = desire_state_updater or DesireStateUpdater()
        self._emotion_state_updater = emotion_state_updater or EmotionStateUpdater()
        self._moral_state_updater = moral_state_updater or MoralStateUpdater()
        self._last_drive_updated_at = initial_time
        self._last_desire_updated_at = initial_time
        self._last_emotion_updated_at = initial_time
        self._last_moral_updated_at = initial_time

    @property
    def last_drive_updated_at(self) -> datetime:
        return self._last_drive_updated_at

    @property
    def last_desire_updated_at(self) -> datetime:
        return self._last_desire_updated_at

    @property
    def last_emotion_updated_at(self) -> datetime:
        return self._last_emotion_updated_at

    @property
    def last_moral_updated_at(self) -> datetime:
        return self._last_moral_updated_at

    def update(self, state: AgentState, *, now: datetime) -> ElapsedStateUpdateResult:
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

        before_desire = state.current_desire
        desire_elapsed_seconds = max(
            0.0,
            (now - self._last_desire_updated_at).total_seconds(),
        )
        after_desire = self._desire_state_updater.update_by_elapsed_time(
            before_desire,
            elapsed_seconds=desire_elapsed_seconds,
        )
        self._last_desire_updated_at = max(self._last_desire_updated_at, now)

        before_drive = state.current_drive
        drive_elapsed_seconds = max(
            0.0,
            (now - self._last_drive_updated_at).total_seconds(),
        )
        after_drive = self._drive_state_updater.derive_by_elapsed_time(
            before_drive,
            emotion=after_emotion,
            desire=after_desire,
            elapsed_seconds=drive_elapsed_seconds,
            activity_active=state.active_activity is not None,
        )
        self._last_drive_updated_at = max(self._last_drive_updated_at, now)

        before_moral = state.current_moral
        moral_elapsed_seconds = max(
            0.0,
            (now - self._last_moral_updated_at).total_seconds(),
        )
        after_moral = self._moral_state_updater.update_by_elapsed_time(
            before_moral,
            profile=state.moral_profile,
            emotion=after_emotion,
            relationship=state.relationship_memory.current,
            elapsed_seconds=moral_elapsed_seconds,
        )
        self._last_moral_updated_at = max(self._last_moral_updated_at, now)

        updated_state = (
            state.with_emotion(after_emotion)
            .with_desire(after_desire)
            .with_drive(after_drive)
            .with_moral(after_moral)
        )
        return ElapsedStateUpdateResult(
            state=updated_state,
            drive_elapsed_seconds=drive_elapsed_seconds,
            desire_elapsed_seconds=desire_elapsed_seconds,
            emotion_elapsed_seconds=emotion_elapsed_seconds,
            moral_elapsed_seconds=moral_elapsed_seconds,
            before_drive=before_drive,
            after_drive=after_drive,
            before_desire=before_desire,
            after_desire=after_desire,
            before_emotion=before_emotion,
            after_emotion=after_emotion,
            before_moral=before_moral,
            after_moral=after_moral,
        )

    def record_event(self, occurred_at: datetime) -> None:
        """Event反映済み状態を派生状態の基準時刻へ反映する。"""

        self._last_desire_updated_at = max(
            self._last_desire_updated_at,
            occurred_at,
        )
        self._last_emotion_updated_at = max(
            self._last_emotion_updated_at,
            occurred_at,
        )
        self._last_moral_updated_at = max(
            self._last_moral_updated_at,
            occurred_at,
        )
