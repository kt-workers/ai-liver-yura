from __future__ import annotations

import math

import pytest

from app.runtime.kernel import (
    LaneErrorPolicy,
    QueuePolicy,
    RuntimeLanePolicy,
    RuntimeSchedulerPolicy,
)


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_scheduler_policy_rejects_invalid_burst(value: object) -> None:
    with pytest.raises(ValueError):
        RuntimeSchedulerPolicy(
            "scheduler",
            1,
            value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_lane_policy_rejects_invalid_counts(value: object) -> None:
    with pytest.raises(ValueError):
        RuntimeLanePolicy(
            "lane",
            value,  # type: ignore[arg-type]
            QueuePolicy.REJECT_NEW,
            1,
            0.0,
            LaneErrorPolicy.ISOLATE,
        )
    with pytest.raises(ValueError):
        RuntimeLanePolicy(
            "lane",
            1,
            QueuePolicy.REJECT_NEW,
            value,  # type: ignore[arg-type]
            0.0,
            LaneErrorPolicy.ISOLATE,
        )


@pytest.mark.parametrize("value", [-1.0, math.inf, -math.inf, math.nan, True])
def test_lane_policy_rejects_invalid_cancellation_grace(value: object) -> None:
    with pytest.raises(ValueError):
        RuntimeLanePolicy(
            "lane",
            1,
            QueuePolicy.REJECT_NEW,
            1,
            value,  # type: ignore[arg-type]
            LaneErrorPolicy.ISOLATE,
        )


def test_lane_and_scheduler_policy_require_explicit_operational_values() -> None:
    with pytest.raises(TypeError):
        RuntimeLanePolicy("lane", 1, QueuePolicy.REJECT_NEW)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RuntimeSchedulerPolicy("scheduler", 1)  # type: ignore[call-arg]
