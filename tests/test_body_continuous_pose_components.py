from __future__ import annotations

import pytest

from app.domain.body_attention import BodyAttentionCandidate
from app.domain.body_attention_intent import (
    BodyAttentionBehavior,
    BodyAttentionIntent,
)
from app.domain.body_auxiliary_projection import BodyTrackingPose
from app.domain.body_motion_state import BodyInnerMotionState
from app.domain.body_pose_dynamics import (
    BodyExternalConstraint,
    BodyPoseAxis,
    BodyPoseConstraintTarget,
    BodyPoseDynamicsState,
)
from app.domain.body_speech import SpeechPresentationRequest
from app.runtime.body_ambient_motion_generator import BodyAmbientMotionGenerator
from app.runtime.body_attention_selector import BodyAttentionSelector
from app.runtime.body_blink_scheduler import BodyBlinkScheduler
from app.runtime.body_breathing_oscillator import BodyBreathingOscillator
from app.runtime.body_external_constraint_player import BodyExternalConstraintPlayer
from app.runtime.body_pose_integrator import BodyPoseIntegrator
from app.runtime.body_speech_mouth_driver import BodySpeechMouthDriver
from app.runtime.body_tick_clock import BodyTickClock

pytestmark = pytest.mark.unit


def _state() -> BodyInnerMotionState:
    return BodyInnerMotionState(
        arousal=0.62,
        tension=0.25,
        curiosity=0.72,
        confidence=0.58,
        engagement=0.78,
        avoidance=0.1,
        movement_energy=0.64,
    )


def test_breathing_oscillator_advances_continuously() -> None:
    oscillator = BodyBreathingOscillator()

    samples = [
        oscillator.step(dt_seconds=1 / 30, state=_state())
        for _ in range(8)
    ]

    assert len({round(sample.body_height, 6) for sample in samples}) > 1
    assert all(abs(sample.body_height) < 0.1 for sample in samples)
    assert oscillator.phase > 0.0


def test_blink_scheduler_forced_blink_closes_and_reopens() -> None:
    scheduler = BodyBlinkScheduler(seed=1)
    scheduler.request_blink()

    openness = [
        scheduler.step(dt_seconds=0.04, state=_state()).eye_open
        for _ in range(10)
    ]

    assert min(openness) < 0.2
    assert openness[-1] == pytest.approx(1.0)
    assert scheduler.blinking is False


def test_ambient_motion_is_seed_deterministic_and_bounded() -> None:
    first = BodyAmbientMotionGenerator(seed=42)
    second = BodyAmbientMotionGenerator(seed=42)

    first_samples = [first.step(dt_seconds=1 / 30, state=_state()) for _ in range(12)]
    second_samples = [second.step(dt_seconds=1 / 30, state=_state()) for _ in range(12)]

    assert first_samples == second_samples
    assert all(-0.82 <= sample.scan_x <= 0.82 for sample in first_samples)
    assert all(-0.58 <= sample.scan_y <= 0.58 for sample in first_samples)


def test_attention_selector_respects_explicit_maintain_target() -> None:
    selector = BodyAttentionSelector(seed=7)
    selector.set_candidates(
        [
            BodyAttentionCandidate("user", 0.15, -0.1, relevance=1.0),
            BodyAttentionCandidate("light", -0.8, 0.2, novelty=1.0),
        ]
    )

    selection = selector.step(
        dt_seconds=1 / 30,
        state=_state(),
        intent=BodyAttentionIntent(
            target="user",
            behavior=BodyAttentionBehavior.MAINTAIN,
            engagement=0.9,
        ),
    )

    assert selection.target_id == "user"
    assert selection.uses_candidate is True
    assert selection.x == pytest.approx(0.15)


def test_attention_selector_avoids_explicit_target_when_requested() -> None:
    selector = BodyAttentionSelector(seed=3)
    selector.set_candidates(
        [
            BodyAttentionCandidate("user", 0.0, 0.0, relevance=1.0),
            BodyAttentionCandidate("window", -0.5, 0.1, salience=0.8),
        ]
    )
    intent = BodyAttentionIntent(
        target="user",
        behavior=BodyAttentionBehavior.AVOID,
        avoidance=1.0,
        engagement=0.4,
    )

    selected_ids = {
        selector.step(dt_seconds=0.1, state=_state(), intent=intent).target_id
        for _ in range(30)
    }

    assert "window" in selected_ids


def test_external_constraint_player_has_attack_and_release_envelope() -> None:
    player = BodyExternalConstraintPlayer()
    player.apply(
        BodyExternalConstraint(
            constraint_id="raise-right-arm",
            targets=(
                BodyPoseConstraintTarget(
                    BodyPoseAxis.RIGHT_ARM_RAISE,
                    1.0,
                ),
            ),
            duration_ms=1000,
            attack_ratio=0.2,
            release_ratio=0.2,
        )
    )

    samples = [player.step(dt_seconds=0.1) for _ in range(10)]

    assert samples[0].envelope < 1.0
    assert max(sample.envelope for sample in samples) == pytest.approx(1.0)
    assert samples[-1].completed is True
    assert samples[-1].envelope == pytest.approx(0.0)
    assert player.active_constraint_id is None


def test_speech_mouth_driver_is_time_bounded() -> None:
    driver = BodySpeechMouthDriver()
    request = SpeechPresentationRequest(
        source_activity_id="activity",
        output_unit_id="unit",
        text="こんにちは",
        audio_reference="memory://audio",
        duration_ms=300,
    )
    driver.present(request, energy=0.8)

    active = driver.step(dt_seconds=0.1)
    completed = driver.step(dt_seconds=0.2)

    assert active.mouth_open > 0.2
    assert active.active_presentation_id == request.presentation_id
    assert completed.completed is True
    assert completed.mouth_open == 0.0
    assert driver.active_presentation_id is None


def test_pose_integrator_approaches_target_without_teleporting() -> None:
    integrator = BodyPoseIntegrator()
    state = BodyPoseDynamicsState()
    target = BodyTrackingPose(right_arm_raise=1.0, head_yaw=0.8)

    first = integrator.step(state=state, target=target, dt_seconds=1 / 30)
    later = first
    for _ in range(60):
        later = integrator.step(
            state=later,
            target=target,
            dt_seconds=1 / 30,
        )

    assert 0.0 < first.pose.right_arm_raise < 1.0
    assert first.pose.head_yaw < 0.8
    assert later.pose.right_arm_raise == pytest.approx(1.0, abs=0.02)
    assert later.pose.head_yaw == pytest.approx(0.8, abs=0.02)


def test_tick_clock_clamps_large_gaps_and_increments_sequence() -> None:
    clock = BodyTickClock(tick_hz=30.0)

    first = clock.next(timestamp_ms=1000)
    second = clock.next(timestamp_ms=5000)

    assert first.sequence == 1
    assert first.dt_seconds == pytest.approx(1 / 30)
    assert second.sequence == 2
    assert second.dt_seconds == 0.1
