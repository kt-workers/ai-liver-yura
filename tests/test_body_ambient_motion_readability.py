from __future__ import annotations

import pytest

from app.domain.body_motion_state import BodyInnerMotionState
from app.runtime.body_ambient_motion_generator import BodyAmbientMotionGenerator

pytestmark = pytest.mark.unit


def _engaged_state() -> BodyInnerMotionState:
    return BodyInnerMotionState(
        arousal=0.62,
        tension=0.25,
        curiosity=0.72,
        confidence=0.58,
        engagement=0.78,
        avoidance=0.1,
        movement_energy=0.64,
    )


def test_ambient_motion_keeps_visible_slow_sway_without_frame_jitter() -> None:
    generator = BodyAmbientMotionGenerator(seed=17)
    samples = [
        generator.step(dt_seconds=1 / 30, state=_engaged_state())
        for _ in range(600)
    ]

    posture_values = [sample.posture_noise for sample in samples]
    head_values = [sample.head_noise for sample in samples]
    posture_deltas = [
        abs(current - previous)
        for previous, current in zip(posture_values, posture_values[1:])
    ]
    head_deltas = [
        abs(current - previous)
        for previous, current in zip(head_values, head_values[1:])
    ]

    assert max(posture_values) - min(posture_values) > 0.08
    assert max(head_values) - min(head_values) > 0.05
    assert max(posture_deltas) <= 0.0022
    assert max(head_deltas) <= 0.0018
    assert all(-0.18 <= value <= 0.18 for value in posture_values)
    assert all(-0.14 <= value <= 0.14 for value in head_values)


def test_ambient_motion_remains_seed_deterministic_with_slow_sway() -> None:
    first = BodyAmbientMotionGenerator(seed=23)
    second = BodyAmbientMotionGenerator(seed=23)

    first_samples = [
        first.step(dt_seconds=1 / 30, state=_engaged_state())
        for _ in range(120)
    ]
    second_samples = [
        second.step(dt_seconds=1 / 30, state=_engaged_state())
        for _ in range(120)
    ]

    assert first_samples == second_samples
