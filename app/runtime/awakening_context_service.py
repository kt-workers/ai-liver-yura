from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from app.domain.awakening import (
    AwakeningCapabilities,
    AwakeningContext,
    AwakeningDesireSnapshot,
    AwakeningDriveSnapshot,
    AwakeningEmotionSnapshot,
    AwakeningInnerStateSnapshot,
    AwakeningSnapshot,
    AwakeningSnapshotLoadStatus,
    AwakeningStartupKind,
)
from app.ports.awakening_snapshot_store import AwakeningSnapshotStore
from app.runtime.agent_state import AgentState
from app.utils.trace import TraceLogger


class AwakeningContextService:
    """前回Snapshotと現在時刻から、起動評価用の事実Contextだけを構築する。"""

    def __init__(
        self,
        store: AwakeningSnapshotStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        resume_window_seconds: float = 1800.0,
    ) -> None:
        if resume_window_seconds <= 0.0:
            raise ValueError("resume_window_seconds must be positive")
        self._store = store
        self._clock = clock
        self._resume_window_seconds = float(resume_window_seconds)
        self._trace = TraceLogger()

    def begin(self, capabilities: AwakeningCapabilities) -> AwakeningContext:
        started_at = self._aware_now()
        try:
            loaded = self._store.load()
        except Exception as error:
            self._trace.warning(
                "awakening_context:load_failed",
                error_type=type(error).__name__,
            )
            return AwakeningContext(
                startup_kind=AwakeningStartupKind.COLD_START,
                started_at=started_at,
                capabilities=capabilities,
                persistence_status=AwakeningSnapshotLoadStatus.IO_ERROR,
                persistence_reason=f"load_failed:{type(error).__name__}",
            )

        snapshot = loaded.snapshot
        if snapshot is None:
            context = AwakeningContext(
                startup_kind=AwakeningStartupKind.COLD_START,
                started_at=started_at,
                capabilities=capabilities,
                persistence_status=loaded.status,
                persistence_reason=loaded.reason,
            )
        else:
            downtime = max(
                0.0,
                (started_at - snapshot.shutdown_at).total_seconds(),
            )
            startup_kind = (
                AwakeningStartupKind.RESUME
                if downtime <= self._resume_window_seconds
                else AwakeningStartupKind.RESTART
            )
            context = AwakeningContext(
                startup_kind=startup_kind,
                started_at=started_at,
                previous_shutdown_at=snapshot.shutdown_at,
                downtime_seconds=downtime,
                previous_inner_state=snapshot.inner_state,
                capabilities=capabilities,
                persistence_status=loaded.status,
                persistence_reason=loaded.reason,
            )
        self._trace.info(
            "awakening_context:built",
            startup_kind=context.startup_kind.value,
            persistence_status=context.persistence_status.value,
            downtime_seconds=context.downtime_seconds,
            body_available=capabilities.body_available,
            tts_available=capabilities.tts_available,
            conversation_output_available=capabilities.conversation_output_available,
        )
        return context

    def save_shutdown_snapshot(self, state: AgentState) -> bool:
        if not isinstance(state, AgentState):
            raise TypeError("state must be AgentState")
        snapshot = AwakeningSnapshot(
            shutdown_at=self._aware_now(),
            inner_state=self._project_inner_state(state),
        )
        try:
            self._store.save(snapshot)
        except Exception as error:
            self._trace.warning(
                "awakening_context:save_failed",
                error_type=type(error).__name__,
            )
            return False
        self._trace.info(
            "awakening_context:snapshot_saved",
            shutdown_at=snapshot.shutdown_at.isoformat(),
        )
        return True

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("awakening clock must return timezone-aware datetime")
        return value

    @staticmethod
    def _project_inner_state(state: AgentState) -> AwakeningInnerStateSnapshot:
        emotion = state.current_emotion
        reactive = emotion.reactive
        drive = state.current_drive
        desire = state.current_desire.effective_values()
        return AwakeningInnerStateSnapshot(
            emotion=AwakeningEmotionSnapshot(
                mood=emotion.mood.value,
                arousal=emotion.arousal,
                valence=emotion.valence,
                talkativeness=emotion.talkativeness,
                joy=reactive.joy,
                amusement=reactive.amusement,
                anger=reactive.anger,
                sadness=reactive.sadness,
                fear=reactive.fear,
                surprise=reactive.surprise,
                discomfort=reactive.discomfort,
                emotional_pressure=reactive.emotional_pressure,
            ),
            drive=AwakeningDriveSnapshot(
                curiosity=drive.curiosity,
                engagement=drive.engagement,
                boredom=drive.boredom,
                energy=drive.energy,
            ),
            desire=AwakeningDesireSnapshot(
                connection=desire["connection"],
                curiosity=desire["curiosity"],
                expression=desire["expression"],
                recognition=desire["recognition"],
                autonomy=desire["autonomy"],
                security=desire["security"],
                achievement=desire["achievement"],
            ),
        )


__all__ = ["AwakeningContextService"]
