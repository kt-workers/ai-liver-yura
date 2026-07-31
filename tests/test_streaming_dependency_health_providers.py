from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.integrations.streaming import (
    DependencyKind,
    DependencyState,
    StreamingCapability,
    StreamingDependencyHealth,
)
from subsystems.streaming.adapters.dependency_health import (
    CompositeDependencyHealthProvider,
    NullDependencyHealthProvider,
    StaticDependencyHealthProvider,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def _health(
    kind: DependencyKind,
    state: DependencyState,
) -> StreamingDependencyHealth:
    available = state in {DependencyState.READY, DependencyState.DEGRADED}
    healthy = state is DependencyState.READY
    capability = {
        DependencyKind.TTS: StreamingCapability.TTS_AVAILABLE,
        DependencyKind.AVATAR: StreamingCapability.AVATAR_AVAILABLE,
    }[kind]
    return StreamingDependencyHealth(
        kind=kind,
        state=state,
        healthy=healthy,
        available=available,
        checked_at=NOW,
        capabilities=frozenset({capability}) if available else frozenset(),
    )


@pytest.mark.parametrize("kind", list(DependencyKind))
def test_null_provider_is_safe_and_disconnected(kind: DependencyKind) -> None:
    provider = NullDependencyHealthProvider(kind, clock=lambda: NOW)
    health = provider.get_health()

    assert health.kind is kind
    assert health.state is DependencyState.DISCONNECTED
    assert health.healthy is False
    assert health.available is False
    assert health.checked_at is NOW


@pytest.mark.parametrize("state", list(DependencyState))
def test_static_provider_supports_every_dependency_state(
    state: DependencyState,
) -> None:
    expected = _health(DependencyKind.TTS, state)
    provider = StaticDependencyHealthProvider(expected)

    assert provider.kind is DependencyKind.TTS
    assert provider.get_health() is expected


class _FailingProvider:
    kind = DependencyKind.TTS

    def get_health(self) -> StreamingDependencyHealth:
        raise RuntimeError("SDK exception and secret must not escape")


def test_composite_is_ordered_and_isolates_provider_failure() -> None:
    avatar = StaticDependencyHealthProvider(
        _health(DependencyKind.AVATAR, DependencyState.READY)
    )
    composite = CompositeDependencyHealthProvider(
        [avatar, _FailingProvider()],
        clock=lambda: NOW,
    )
    values = composite.list_health()

    assert tuple(value.kind for value in values) == (
        DependencyKind.TTS,
        DependencyKind.AVATAR,
    )
    assert values[0].state is DependencyState.ERROR
    assert values[0].message == "tts_health_check_failed"
    assert "secret" not in repr(values[0])
    assert values[1].state is DependencyState.READY


def test_composite_fills_missing_kind_with_disconnected_health() -> None:
    composite = CompositeDependencyHealthProvider(clock=lambda: NOW)

    assert tuple(value.state for value in composite.list_health()) == (
        DependencyState.DISCONNECTED,
        DependencyState.DISCONNECTED,
    )


def test_composite_rejects_duplicate_kind() -> None:
    health = _health(DependencyKind.TTS, DependencyState.READY)
    with pytest.raises(ValueError, match="duplicate"):
        CompositeDependencyHealthProvider(
            [
                StaticDependencyHealthProvider(health),
                StaticDependencyHealthProvider(health),
            ]
        )
