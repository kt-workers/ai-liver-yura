from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.adapters.avatar.body_pose_http_config import HttpBodyPoseOutputConfig
from app.adapters.avatar.http_body_pose_output import HttpBodyPoseFrameOutput
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
from app.domain.awakening_state import AwakeningLifecyclePhase, AwakeningState
from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.runtime.agent_state import AgentState
from app.runtime.awakening_state_transition_service import AwakeningStateTransitionService
from app.runtime.body_awakening_affect_projector import BodyAwakeningAffectProjector
from app.runtime.body_emotion_state_store import LatestBodyEmotionStateStore
from app.runtime.state_driven_body_pose_runtime import StateDrivenBodyPoseRuntime
from tests.support.body_pose_lab_http_harness import BodyPoseLabHttpHarness

NOW = datetime(2026, 8, 7, 6, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class _StartupProfile:
    name: str
    startup_kind: AwakeningStartupKind
    downtime_seconds: float
    energy: float
    arousal: float
    curiosity: float
    security: float
    talkativeness: float = 0.5
    engagement: float = 0.5
    persistence_status: AwakeningSnapshotLoadStatus = AwakeningSnapshotLoadStatus.LOADED


def _startup_event(profile: _StartupProfile) -> AgentEvent:
    previous = AwakeningInnerStateSnapshot(
        emotion=AwakeningEmotionSnapshot(
            mood="neutral",
            arousal=profile.arousal,
            valence=0.10,
            talkativeness=profile.talkativeness,
        ),
        drive=AwakeningDriveSnapshot(
            curiosity=profile.curiosity,
            engagement=profile.engagement,
            boredom=max(0.0, 1.0 - profile.engagement),
            energy=profile.energy,
        ),
        desire=AwakeningDesireSnapshot(
            connection=profile.engagement,
            curiosity=profile.curiosity,
            expression=profile.talkativeness,
            recognition=0.4,
            autonomy=0.55,
            security=profile.security,
            achievement=profile.curiosity,
        ),
    )
    context = AwakeningContext(
        startup_kind=profile.startup_kind,
        started_at=NOW,
        capabilities=AwakeningCapabilities(
            body_available=True,
            tts_available=True,
            conversation_output_available=True,
        ),
        persistence_status=profile.persistence_status,
        previous_shutdown_at=NOW - timedelta(seconds=profile.downtime_seconds),
        downtime_seconds=profile.downtime_seconds,
        previous_inner_state=previous,
    )
    return AgentEvent(
        event_type=AgentEventType.APP_STARTED,
        payload={
            "source": "awakening-http-sse-final-integration",
            "awakening_context": context.as_context(),
        },
        occurred_at=NOW,
        authority=InputAuthority.SYSTEM,
        discardable=False,
    )


async def _wait_for_sent(output: HttpBodyPoseFrameOutput) -> None:
    for _ in range(200):
        if output.snapshot().sent_count >= 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("BodyPoseFrame did not reach Body Pose Lab")


async def _publish_state_over_real_http_sse(
    harness: BodyPoseLabHttpHarness,
    *,
    emotion_store: LatestBodyEmotionStateStore,
    source_name: str,
) -> tuple[dict[str, object], dict[str, float]]:
    output = HttpBodyPoseFrameOutput(
        HttpBodyPoseOutputConfig(
            base_url=harness.base_url,
            timeout_seconds=1.0,
            source_name=source_name,
        )
    )
    runtime = BodyRuntimeFactory().create(
        settings=BodyRuntimeSettings(enabled=True, random_seed=17),
        avatar_output=None,
        pose_output=output,
        emotion_provider=emotion_store.snapshot,
        awakening_provider=emotion_store.awakening_snapshot,
    )
    assert isinstance(runtime, StateDrivenBodyPoseRuntime)
    try:
        frame = await runtime.tick_once()
        await _wait_for_sent(output)
        event_name, payload = harness.first_sse_event()
        assert event_name == "body-pose-frame"
        assert payload["source"] == source_name
        inner_state = payload["inner_state"]
        assert isinstance(inner_state, dict)
        expected = frame.inner_state.as_payload()
        assert inner_state == pytest.approx(expected)
        return payload, {str(key): float(value) for key, value in inner_state.items()}
    finally:
        await output.close()


def _transition(profile: _StartupProfile):
    event = _startup_event(profile)
    transition = AwakeningStateTransitionService().transition(AgentState(), event)
    assert transition is not None
    return event, transition


def _phase_state(base: AwakeningState, phase: AwakeningLifecyclePhase) -> AwakeningState:
    if phase is AwakeningLifecyclePhase.INITIALIZING:
        return base
    if phase is AwakeningLifecyclePhase.WAKING:
        return base.transition(phase, at=NOW + timedelta(milliseconds=1))
    waking = base.transition(
        AwakeningLifecyclePhase.WAKING,
        at=NOW + timedelta(milliseconds=1),
    )
    if phase is AwakeningLifecyclePhase.ORIENTING:
        return waking.transition(phase, at=NOW + timedelta(seconds=1))
    orienting = waking.transition(
        AwakeningLifecyclePhase.ORIENTING,
        at=NOW + timedelta(seconds=1),
    )
    return orienting.transition(
        AwakeningLifecyclePhase.READY,
        at=NOW + timedelta(seconds=2),
    )


@pytest.mark.asyncio
async def test_seeded_initial_frame_reaches_real_body_pose_lab_sse() -> None:
    profile = _StartupProfile(
        name="eager",
        startup_kind=AwakeningStartupKind.RESUME,
        downtime_seconds=180.0,
        energy=0.94,
        arousal=0.88,
        curiosity=0.96,
        security=0.08,
        talkativeness=0.74,
        engagement=0.84,
    )
    event = _startup_event(profile)
    store = LatestBodyEmotionStateStore()
    assert prime_body_causal_state_from_startup(
        state=AgentState(),
        event=event,
        store=store,
    )

    neutral_store = LatestBodyEmotionStateStore()
    with BodyPoseLabHttpHarness.start(local_simulation=False) as harness:
        _, initial = await _publish_state_over_real_http_sse(
            harness,
            emotion_store=store,
            source_name="awakening-initial",
        )
        _, neutral = await _publish_state_over_real_http_sse(
            harness,
            emotion_store=neutral_store,
            source_name="awakening-neutral-reference",
        )

    assert initial != neutral
    assert initial["arousal"] > neutral["arousal"]
    assert initial["curiosity"] > neutral["curiosity"]
    assert initial["movement_energy"] > neutral["movement_energy"]


@pytest.mark.asyncio
async def test_awaking_lifecycle_and_context_differences_reach_real_sse() -> None:
    eager = _StartupProfile(
        name="eager",
        startup_kind=AwakeningStartupKind.RESUME,
        downtime_seconds=180.0,
        energy=0.95,
        arousal=0.90,
        curiosity=0.96,
        security=0.08,
        talkativeness=0.72,
        engagement=0.86,
    )
    drowsy = _StartupProfile(
        name="drowsy",
        startup_kind=AwakeningStartupKind.RESUME,
        downtime_seconds=90.0,
        energy=0.10,
        arousal=0.12,
        curiosity=0.30,
        security=0.18,
        talkativeness=0.18,
        engagement=0.28,
    )
    refreshed = _StartupProfile(
        name="refreshed",
        startup_kind=AwakeningStartupKind.RESTART,
        downtime_seconds=8 * 3600.0,
        energy=0.68,
        arousal=0.66,
        curiosity=0.62,
        security=0.16,
        talkativeness=0.56,
        engagement=0.64,
    )
    cautious = _StartupProfile(
        name="cautious",
        startup_kind=AwakeningStartupKind.RESTART,
        downtime_seconds=240.0,
        energy=0.52,
        arousal=0.56,
        curiosity=0.42,
        security=0.96,
        talkativeness=0.34,
        engagement=0.46,
    )

    _, eager_transition = _transition(eager)
    phase_states = {
        phase: _phase_state(eager_transition.awakening_state, phase)
        for phase in (
            AwakeningLifecyclePhase.WAKING,
            AwakeningLifecyclePhase.ORIENTING,
            AwakeningLifecyclePhase.READY,
        )
    }
    projector = BodyAwakeningAffectProjector()

    with BodyPoseLabHttpHarness.start(local_simulation=False) as harness:
        phase_inner: dict[AwakeningLifecyclePhase, dict[str, float]] = {}
        for phase, awakening_state in phase_states.items():
            store = LatestBodyEmotionStateStore()
            store.update(
                eager_transition.projection.emotion,
                awakening=projector.project(awakening_state),
            )
            _, phase_inner[phase] = await _publish_state_over_real_http_sse(
                harness,
                emotion_store=store,
                source_name=f"awakening-phase-{phase.value}",
            )

        scenario_signatures: set[tuple[float, ...]] = set()
        for profile in (refreshed, drowsy, eager, cautious):
            event, transition = _transition(profile)
            store = LatestBodyEmotionStateStore()
            assert prime_body_causal_state_from_startup(
                state=AgentState(),
                event=event,
                store=store,
            )
            _, inner = await _publish_state_over_real_http_sse(
                harness,
                emotion_store=store,
                source_name=f"awakening-scenario-{profile.name}",
            )
            scenario_signatures.add(
                tuple(round(inner[key], 6) for key in sorted(inner))
            )

    waking = phase_inner[AwakeningLifecyclePhase.WAKING]
    orienting = phase_inner[AwakeningLifecyclePhase.ORIENTING]
    ready = phase_inner[AwakeningLifecyclePhase.READY]
    assert waking["arousal"] > orienting["arousal"] > ready["arousal"]
    assert waking["curiosity"] > orienting["curiosity"] > ready["curiosity"]
    assert waking["movement_energy"] > orienting["movement_energy"] > ready["movement_energy"]
    assert len(scenario_signatures) == 4
