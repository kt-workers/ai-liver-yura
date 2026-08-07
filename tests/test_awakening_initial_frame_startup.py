from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.bootstrap.body_runtime_factory import BodyRuntimeFactory
from app.bootstrap.body_runtime_settings import BodyRuntimeSettings
from app.bootstrap.body_runtime_setup import prime_body_causal_state_from_startup
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
from app.domain.body_pose_frame import BodyPoseFrame
from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_state import AgentState
from app.runtime.body_awakening_affect_projector import BodyAwakeningAffectProjector
from app.runtime.body_emotion_state_store import LatestBodyEmotionStateStore
from app.runtime.state_driven_body_pose_runtime import StateDrivenBodyPoseRuntime

NOW = datetime(2026, 8, 7, 5, 30, tzinfo=timezone.utc)


class _PoseOutput:
    def __init__(self) -> None:
        self.frames: list[BodyPoseFrame] = []
        self.closed = False

    async def publish_body_pose_frame(self, frame: BodyPoseFrame) -> None:
        self.frames.append(frame)

    async def close(self) -> None:
        self.closed = True


def _startup_event() -> AgentEvent:
    previous = AwakeningInnerStateSnapshot(
        emotion=AwakeningEmotionSnapshot(
            mood="neutral",
            arousal=0.86,
            valence=0.34,
            talkativeness=0.76,
            joy=0.18,
        ),
        drive=AwakeningDriveSnapshot(
            curiosity=0.92,
            engagement=0.82,
            boredom=0.04,
            energy=0.90,
        ),
        desire=AwakeningDesireSnapshot(
            connection=0.72,
            curiosity=0.94,
            expression=0.68,
            recognition=0.42,
            autonomy=0.58,
            security=0.16,
            achievement=0.74,
        ),
    )
    context = AwakeningContext(
        startup_kind=AwakeningStartupKind.RESUME,
        started_at=NOW,
        capabilities=AwakeningCapabilities(
            body_available=True,
            tts_available=True,
            conversation_output_available=True,
        ),
        persistence_status=AwakeningSnapshotLoadStatus.LOADED,
        previous_shutdown_at=NOW - timedelta(minutes=4),
        downtime_seconds=240.0,
        previous_inner_state=previous,
    )
    return AgentEvent(
        event_type=AgentEventType.APP_STARTED,
        payload={
            "source": "test",
            "awakening_context": context.as_context(),
        },
        occurred_at=NOW,
        authority=InputAuthority.SYSTEM,
        discardable=False,
    )


def test_startup_body_seed_matches_runtime_awakening_projection() -> None:
    state = AgentState()
    event = _startup_event()
    store = LatestBodyEmotionStateStore()

    assert prime_body_causal_state_from_startup(
        state=state,
        event=event,
        store=store,
    )

    expected = AgentEventStateUpdater().update(state, event).state
    expected_awakening = BodyAwakeningAffectProjector().project(
        expected.awakening_state
    )

    assert store.snapshot() == expected.current_emotion
    assert store.awakening_snapshot() == expected_awakening
    assert store.awakening_snapshot().salience == 1.0
    assert store.awakening_snapshot().activation > 0.5


@pytest.mark.asyncio
async def test_first_body_tick_uses_startup_seed_even_when_runtime_was_built_first() -> None:
    state = AgentState()
    event = _startup_event()
    store = LatestBodyEmotionStateStore()
    output = _PoseOutput()
    runtime = BodyRuntimeFactory().create(
        settings=BodyRuntimeSettings(enabled=True, random_seed=7),
        avatar_output=None,
        pose_output=output,
        emotion_provider=store.snapshot,
        awakening_provider=store.awakening_snapshot,
    )
    assert isinstance(runtime, StateDrivenBodyPoseRuntime)

    neutral_output = _PoseOutput()
    neutral_store = LatestBodyEmotionStateStore()
    neutral_runtime = BodyRuntimeFactory().create(
        settings=BodyRuntimeSettings(enabled=True, random_seed=7),
        avatar_output=None,
        pose_output=neutral_output,
        emotion_provider=neutral_store.snapshot,
        awakening_provider=neutral_store.awakening_snapshot,
    )
    assert isinstance(neutral_runtime, StateDrivenBodyPoseRuntime)

    assert prime_body_causal_state_from_startup(
        state=state,
        event=event,
        store=store,
    )

    first_frame = await runtime.tick_once()
    neutral_frame = await neutral_runtime.tick_once()

    assert output.frames == [first_frame]
    assert neutral_output.frames == [neutral_frame]
    assert first_frame.inner_state != neutral_frame.inner_state
    assert first_frame.inner_state.arousal > neutral_frame.inner_state.arousal
    assert first_frame.inner_state.curiosity > neutral_frame.inner_state.curiosity
    assert first_frame.inner_state.movement_energy > neutral_frame.inner_state.movement_energy


@pytest.mark.parametrize(
    "event",
    [
        AgentEvent(
            event_type=AgentEventType.APP_STARTED,
            payload={"source": "test"},
            occurred_at=NOW,
            authority=InputAuthority.SYSTEM,
        ),
    ],
)
def test_startup_body_seed_without_awakening_context_is_safe(event: AgentEvent) -> None:
    store = LatestBodyEmotionStateStore()
    before = store.causal_snapshot()

    assert not prime_body_causal_state_from_startup(
        state=AgentState(),
        event=event,
        store=store,
    )
    assert store.causal_snapshot() == before


def test_startup_body_seed_rejects_non_startup_event() -> None:
    with pytest.raises(ValueError, match="APP_STARTED"):
        prime_body_causal_state_from_startup(
            state=AgentState(),
            event=AgentEvent(
                event_type=AgentEventType.USER_TEXT,
                payload={"text": "hello"},
                occurred_at=NOW,
                authority=InputAuthority.USER,
            ),
            store=LatestBodyEmotionStateStore(),
        )
