from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

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
from app.domain.awakening_state import (
    AwakeningLifecyclePhase,
    AwakeningState,
)
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState, MoodType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_state import AgentState
from app.runtime.awakening_appraiser import AwakeningAppraiser
from app.runtime.awakening_aware_agent_life_service import AwakeningAwareAgentLifeService
from app.runtime.awakening_lifecycle_policy import AwakeningLifecyclePolicy
from app.runtime.awakening_state_projector import AwakeningStateProjector

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 3, 0, tzinfo=UTC)


def _previous(
    *,
    energy: float = 0.7,
    arousal: float = 0.6,
    talkativeness: float = 0.55,
    curiosity: float = 0.6,
    engagement: float = 0.55,
    security: float = 0.35,
    joy: float = 0.1,
    sadness: float = 0.0,
) -> AwakeningInnerStateSnapshot:
    return AwakeningInnerStateSnapshot(
        emotion=AwakeningEmotionSnapshot(
            mood="neutral",
            arousal=arousal,
            valence=0.05,
            talkativeness=talkativeness,
            joy=joy,
            sadness=sadness,
        ),
        drive=AwakeningDriveSnapshot(
            curiosity=curiosity,
            engagement=engagement,
            boredom=0.12,
            energy=energy,
        ),
        desire=AwakeningDesireSnapshot(
            connection=0.55,
            curiosity=curiosity,
            expression=0.5,
            recognition=0.3,
            autonomy=0.4,
            security=security,
            achievement=0.4,
        ),
    )


def _context(
    *,
    kind: AwakeningStartupKind = AwakeningStartupKind.RESTART,
    downtime_seconds: float = 8 * 3600,
    previous: AwakeningInnerStateSnapshot | None = None,
    body: bool = True,
    tts: bool = True,
    output: bool = True,
) -> AwakeningContext:
    return AwakeningContext(
        startup_kind=kind,
        started_at=NOW,
        previous_shutdown_at=(
            NOW - timedelta(seconds=downtime_seconds)
            if previous is not None
            else None
        ),
        downtime_seconds=(downtime_seconds if previous is not None else None),
        previous_inner_state=previous,
        capabilities=AwakeningCapabilities(
            body_available=body,
            tts_available=tts,
            conversation_output_available=output,
        ),
        persistence_status=(
            AwakeningSnapshotLoadStatus.LOADED
            if previous is not None
            else AwakeningSnapshotLoadStatus.MISSING
        ),
    )


def test_long_rest_is_not_forced_to_refreshed_when_previous_energy_was_low() -> None:
    appraisal = AwakeningAppraiser().appraise(
        _context(
            previous=_previous(energy=0.12, arousal=0.18, talkativeness=0.25),
            downtime_seconds=8 * 3600,
        )
    )

    assert appraisal.restoration > 0.75
    assert appraisal.sleepiness > 0.5
    assert appraisal.activation_urge < 0.65
    assert appraisal.readiness < 0.75


def test_high_curiosity_and_energy_produce_exploration_and_activation_urges() -> None:
    appraisal = AwakeningAppraiser().appraise(
        _context(
            kind=AwakeningStartupKind.RESUME,
            previous=_previous(
                energy=0.92,
                arousal=0.82,
                talkativeness=0.7,
                curiosity=0.94,
                engagement=0.82,
            ),
            downtime_seconds=6 * 60,
        )
    )

    assert appraisal.activation_urge > 0.7
    assert appraisal.exploration_urge > 0.8
    assert appraisal.sleepiness < 0.3
    assert appraisal.social_urge > 0.55


def test_capability_loss_increases_security_and_orientation_without_forcing_fear() -> None:
    appraiser = AwakeningAppraiser()
    healthy = appraiser.appraise(_context(previous=_previous()))
    degraded = appraiser.appraise(
        _context(previous=_previous(), body=False, tts=False, output=True)
    )

    assert degraded.security_need > healthy.security_need
    assert degraded.orientation_need > healthy.orientation_need


def test_short_resume_carries_previous_affect_more_than_long_restart() -> None:
    previous = _previous(joy=0.7, sadness=0.2)
    appraiser = AwakeningAppraiser()
    short = appraiser.appraise(
        _context(
            kind=AwakeningStartupKind.RESUME,
            downtime_seconds=5 * 60,
            previous=previous,
        )
    )
    long = appraiser.appraise(
        _context(
            kind=AwakeningStartupKind.RESTART,
            downtime_seconds=8 * 3600,
            previous=previous,
        )
    )

    assert short.residual_affect_weight > 0.9
    assert long.residual_affect_weight < 0.1


def test_projection_can_be_sleepy_without_erasing_curiosity_desire() -> None:
    context = _context(
        previous=_previous(
            energy=0.1,
            arousal=0.18,
            talkativeness=0.22,
            curiosity=0.86,
        )
    )
    appraisal = AwakeningAppraiser().appraise(context)
    projection = AwakeningStateProjector().project(
        context=context,
        appraisal=appraisal,
        emotion=EmotionState(),
        desire=AgentState().current_desire,
        drive=DriveState(),
    )

    assert projection.emotion.mood is MoodType.TIRED
    assert projection.drive.curiosity > 0.55
    assert projection.desire.curiosity.effective_level > 0.5
    assert projection.drive.energy < 0.65


def test_projection_can_be_activated_without_forcing_happy_mood() -> None:
    context = _context(
        kind=AwakeningStartupKind.RESUME,
        downtime_seconds=5 * 60,
        previous=_previous(
            energy=0.95,
            arousal=0.9,
            curiosity=0.95,
            joy=0.0,
            sadness=0.0,
        ),
    )
    appraisal = AwakeningAppraiser().appraise(context)
    projection = AwakeningStateProjector().project(
        context=context,
        appraisal=appraisal,
        emotion=EmotionState(),
        desire=AgentState().current_desire,
        drive=DriveState(),
    )

    assert projection.drive.energy > 0.65
    assert projection.drive.curiosity > 0.75
    assert projection.emotion.mood in {MoodType.EXCITED, MoodType.NEUTRAL}
    assert projection.emotion.reactive.joy < 0.1


def test_lifecycle_duration_is_derived_from_appraisal() -> None:
    appraiser = AwakeningAppraiser()
    energetic_appraisal = appraiser.appraise(
        _context(
            kind=AwakeningStartupKind.RESUME,
            downtime_seconds=5 * 60,
            previous=_previous(energy=0.95, arousal=0.9, curiosity=0.9),
        )
    )
    sleepy_appraisal = appraiser.appraise(
        _context(
            previous=_previous(energy=0.1, arousal=0.15, talkativeness=0.2),
        )
    )
    policy = AwakeningLifecyclePolicy()
    energetic = AwakeningState(
        phase=AwakeningLifecyclePhase.WAKING,
        appraisal=energetic_appraisal,
        started_at=NOW,
        phase_started_at=NOW,
    )
    sleepy = AwakeningState(
        phase=AwakeningLifecyclePhase.WAKING,
        appraisal=sleepy_appraisal,
        started_at=NOW,
        phase_started_at=NOW,
    )

    at = NOW + timedelta(seconds=1.5)
    assert policy.advance(energetic, now=at).phase is AwakeningLifecyclePhase.ORIENTING
    assert policy.advance(sleepy, now=at).phase is AwakeningLifecyclePhase.WAKING


def test_app_started_updates_inner_state_and_records_awakening_state() -> None:
    context = _context(
        kind=AwakeningStartupKind.RESUME,
        downtime_seconds=4 * 60,
        previous=_previous(energy=0.9, arousal=0.85, curiosity=0.9),
    )
    event = AgentEvent(
        AgentEventType.APP_STARTED,
        payload={"source": "test", "awakening_context": context.as_context()},
        occurred_at=NOW,
    )

    result = AgentEventStateUpdater().update(AgentState(), event)

    assert result.state.awakening_state is not None
    assert result.state.awakening_state.phase is AwakeningLifecyclePhase.INITIALIZING
    assert result.appraisal.reason == "awakening_appraisal"
    assert result.after_drive != result.before_drive
    assert result.after_emotion != result.before_emotion


def test_app_started_without_new_context_keeps_legacy_behavior() -> None:
    event = AgentEvent(
        AgentEventType.APP_STARTED,
        payload={"source": "legacy-test"},
        occurred_at=NOW,
    )

    result = AgentEventStateUpdater().update(AgentState(), event)

    assert result.state.awakening_state is None


def test_life_service_advances_initializing_to_waking_without_fixed_motion() -> None:
    appraisal = AwakeningAppraiser().appraise(
        _context(previous=_previous())
    )
    initial = AgentState().with_awakening_state(
        AwakeningState(
            phase=AwakeningLifecyclePhase.INITIALIZING,
            appraisal=appraisal,
            started_at=NOW,
            phase_started_at=NOW,
        )
    )
    service = AwakeningAwareAgentLifeService(
        MagicMock(),
        initial_state=initial,
        now=NOW,
    )

    service._advance_awakening(NOW)

    assert service.agent_state.awakening_state is not None
    assert service.agent_state.awakening_state.phase is AwakeningLifecyclePhase.WAKING
