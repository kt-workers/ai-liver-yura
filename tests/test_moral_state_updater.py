import pytest

from app.domain.emotions import EmotionState, ReactiveEmotionState
from app.domain.events import AgentEvent, AgentEventType
from app.domain.morals import MoralProfile, MoralState
from app.runtime.moral_state_updater import MoralStateUpdater


def test_anger_raises_aggressive_impulse_without_disabling_restraint() -> None:
    profile = MoralProfile()
    current = MoralState.from_profile(profile)
    emotion = EmotionState(
        reactive=ReactiveEmotionState(anger=1.0, discomfort=0.4),
    )

    updated = MoralStateUpdater().update_by_event(
        current,
        AgentEvent(event_type=AgentEventType.CAMERA_FRAME),
        profile=profile,
        emotion=emotion,
    )

    assert updated.aggressive_impulse > current.aggressive_impulse
    assert 0.0 <= updated.restraint <= 1.0


def test_failed_activity_increases_guilt() -> None:
    profile = MoralProfile()
    current = MoralState.from_profile(profile)
    event = AgentEvent(
        event_type=AgentEventType.ACTIVITY_RESULT_RECORDED,
        payload={"outcome": "failed"},
    )

    updated = MoralStateUpdater().update_by_event(
        current,
        event,
        profile=profile,
        emotion=EmotionState(),
    )

    assert updated.guilt > current.guilt
    assert updated.restraint >= current.restraint


def test_completed_activity_eases_guilt_and_aggressive_impulse() -> None:
    profile = MoralProfile()
    current = MoralState.from_profile(profile).adjusted(
        guilt=0.3,
        aggressive_impulse=0.3,
    )
    event = AgentEvent(
        event_type=AgentEventType.ACTIVITY_RESULT_RECORDED,
        payload={"outcome": "completed"},
    )

    updated = MoralStateUpdater().update_by_event(
        current,
        event,
        profile=profile,
        emotion=EmotionState(),
    )

    assert updated.guilt < current.guilt
    assert updated.aggressive_impulse < current.aggressive_impulse


def test_elapsed_time_returns_state_toward_profile_baseline() -> None:
    profile = MoralProfile()
    baseline = MoralState.from_profile(profile)
    current = baseline.adjusted(
        selfish_impulse=0.4,
        aggressive_impulse=0.4,
        guilt=0.4,
    )

    updated = MoralStateUpdater().update_by_elapsed_time(
        current,
        profile=profile,
        emotion=EmotionState(),
        elapsed_seconds=900.0,
    )

    assert updated.restraint == pytest.approx(baseline.restraint)
    assert updated.empathy_activation == pytest.approx(
        baseline.empathy_activation
    )
    assert updated.selfish_impulse == pytest.approx(baseline.selfish_impulse)
    assert updated.aggressive_impulse == pytest.approx(
        baseline.aggressive_impulse
    )
    assert updated.guilt == pytest.approx(baseline.guilt)
