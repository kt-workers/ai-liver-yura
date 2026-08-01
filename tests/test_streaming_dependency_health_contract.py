from __future__ import annotations

import operator
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.integrations.streaming import (
    DependencyKind,
    DependencyState,
    StreamingCapability,
    StreamingDependencyHealth,
    normalize_dependency_state,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("disconnected", DependencyState.DISCONNECTED),
        ("unavailable", DependencyState.UNAVAILABLE),
        ("ready", DependencyState.READY),
        ("degraded", DependencyState.DEGRADED),
        ("error", DependencyState.ERROR),
        ("future_state", DependencyState.DEGRADED),
    ],
)
def test_dependency_states_are_stable_and_unknown_is_degraded(
    value: str,
    expected: DependencyState,
) -> None:
    assert normalize_dependency_state(value) is expected


def test_health_defensively_freezes_json_metadata() -> None:
    metadata: dict[str, object] = {
        "version": "1",
        "latency_ms": 12,
        "features": ["speech", {"rendering": True}],
    }
    health = StreamingDependencyHealth(
        kind=DependencyKind.TTS,
        state=DependencyState.READY,
        healthy=True,
        available=True,
        checked_at=NOW,
        capabilities=frozenset({StreamingCapability.TTS_AVAILABLE}),
        metadata=metadata,
    )

    metadata["version"] = "changed"
    features = metadata["features"]
    assert isinstance(features, list)
    features.append("changed")

    assert health.metadata["version"] == "1"
    assert health.metadata["features"] == ("speech", {"rendering": True})
    with pytest.raises(TypeError):
        operator.setitem(health.metadata, "version", "changed")
    with pytest.raises(FrozenInstanceError):
        health.healthy = False


@pytest.mark.parametrize(
    "metadata",
    [
        {"speaker_id": 1},
        {"endpoint": "http://127.0.0.1"},
        {"model_path": "/models/avatar"},
        {"cubism_parameter_id": "ParamMouthOpenY"},
        {"sdk_response": object()},
        {"latency_ms": float("nan")},
    ],
)
def test_health_rejects_sdk_specific_or_non_json_metadata(
    metadata: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        StreamingDependencyHealth(
            kind=DependencyKind.AVATAR,
            state=DependencyState.DEGRADED,
            healthy=False,
            available=True,
            checked_at=NOW,
            metadata=metadata,
        )


def test_health_validates_timestamp_availability_and_capability_kind() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        StreamingDependencyHealth(
            kind=DependencyKind.TTS,
            state=DependencyState.DISCONNECTED,
            healthy=False,
            available=False,
            checked_at=datetime(2026, 7, 31),
        )
    with pytest.raises(ValueError, match="another kind"):
        StreamingDependencyHealth(
            kind=DependencyKind.TTS,
            state=DependencyState.READY,
            healthy=True,
            available=True,
            checked_at=NOW,
            capabilities=frozenset({StreamingCapability.AVATAR_AVAILABLE}),
        )
