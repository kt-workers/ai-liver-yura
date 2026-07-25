from __future__ import annotations

import pytest

from app.runtime.processed_event_registry import ProcessedEventRegistry


def test_register_accepts_new_event_and_rejects_duplicate() -> None:
    registry = ProcessedEventRegistry(capacity=3)

    assert registry.register("event-1") is True
    assert registry.register("event-1") is False
    assert registry.contains("event-1") is True


def test_register_evicts_oldest_event_when_capacity_is_reached() -> None:
    registry = ProcessedEventRegistry(capacity=2)

    registry.register("event-1")
    registry.register("event-2")
    registry.register("event-3")

    assert registry.contains("event-1") is False
    assert registry.contains("event-2") is True
    assert registry.contains("event-3") is True


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="capacity"):
        ProcessedEventRegistry(capacity=0)
