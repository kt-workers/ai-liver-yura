from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.contracts import CapabilityAvailability, RevisionVector
from app.domain.input_gateway import (
    ContactPercept,
    ContactTargetKind,
    InputAdmissionStatus,
    InputModality,
    InputNormalizer,
    InputObservation,
    InputPermission,
    InputRejectionReason,
    InputSessionPhase,
    InputSessionSample,
    InputSourceState,
    PointerSample,
)

NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)


def source(
    *,
    availability: CapabilityAvailability = CapabilityAvailability.AVAILABLE,
    permission: InputPermission = InputPermission.GRANTED,
) -> InputSourceState:
    return InputSourceState("source-1", "gui", availability, permission, "cap-input")


def observation(
    observation_id: str,
    *,
    input_source: InputSourceState | None = None,
    modality: InputModality = InputModality.TEXT,
    session: InputSessionSample | None = None,
) -> InputObservation:
    return InputObservation(
        observation_id,
        input_source or source(),
        modality,
        "utterance",
        NOW,
        "trace-1",
        RevisionVector(3, goal_revision=2),
        {"text": "こんにちは"},
        correlation_id="conversation-1",
        session=session,
    )


def test_normalizes_source_neutral_foundation_event_without_meaning() -> None:
    result = InputNormalizer().normalize(observation("obs-1"))
    assert result.status is InputAdmissionStatus.ACCEPTED
    assert result.event is not None
    envelope = result.event.envelope
    assert envelope.event_id == "input:obs-1"
    assert envelope.event_type == "input.text.utterance"
    assert envelope.source == "source-1"
    assert envelope.occurred_at == NOW
    assert envelope.correlation_id == "conversation-1"
    payload = cast(Mapping[str, object], envelope.payload)
    content = cast(Mapping[str, object], payload["content"])
    assert content["text"] == "こんにちは"
    assert "intent" not in payload
    assert "emotion" not in payload


def test_duplicate_observation_is_idempotently_rejected_even_after_failure() -> None:
    normalizer = InputNormalizer()
    unavailable = observation(
        "same",
        input_source=source(availability=CapabilityAvailability.UNAVAILABLE),
    )
    first = normalizer.normalize(unavailable)
    second = normalizer.normalize(observation("same"))
    assert first.reason is InputRejectionReason.SOURCE_UNAVAILABLE
    assert second.status is InputAdmissionStatus.DUPLICATE
    assert second.reason is InputRejectionReason.DUPLICATE


@pytest.mark.parametrize(
    ("input_source", "reason"),
    [
        (
            source(availability=CapabilityAvailability.UNAVAILABLE),
            InputRejectionReason.SOURCE_UNAVAILABLE,
        ),
        (source(permission=InputPermission.DENIED), InputRejectionReason.PERMISSION_DENIED),
        (source(permission=InputPermission.UNKNOWN), InputRejectionReason.PERMISSION_UNKNOWN),
    ],
)
def test_source_state_fails_closed(
    input_source: InputSourceState, reason: InputRejectionReason
) -> None:
    result = InputNormalizer().normalize(observation("obs", input_source=input_source))
    assert result.status is InputAdmissionStatus.REJECTED
    assert result.reason is reason


def test_lifecycle_event_reports_unavailable_source_without_fabricating_input() -> None:
    lifecycle = observation(
        "source-state",
        input_source=source(
            availability=CapabilityAvailability.UNAVAILABLE,
            permission=InputPermission.DENIED,
        ),
        modality=InputModality.LIFECYCLE,
    )
    result = InputNormalizer().normalize(lifecycle)
    assert result.event is not None
    assert result.event.envelope.event_type == "input.lifecycle.utterance"
    assert result.event.source.availability is CapabilityAvailability.UNAVAILABLE


def test_continuous_session_accepts_strict_lifecycle() -> None:
    normalizer = InputNormalizer()
    phases = [
        InputSessionSample("gesture", InputSessionPhase.START, 0),
        InputSessionSample("gesture", InputSessionPhase.UPDATE, 1),
        InputSessionSample("gesture", InputSessionPhase.UPDATE, 3),
        InputSessionSample("gesture", InputSessionPhase.END, 4),
    ]
    for index, sample in enumerate(phases):
        result = normalizer.normalize(observation(f"obs-{index}", session=sample))
        assert result.status is InputAdmissionStatus.ACCEPTED


def test_session_rejects_missing_duplicate_out_of_order_and_terminal_samples() -> None:
    normalizer = InputNormalizer()
    missing = normalizer.normalize(
        observation("missing", session=InputSessionSample("g", InputSessionPhase.UPDATE, 1))
    )
    assert missing.reason is InputRejectionReason.SESSION_NOT_ACTIVE

    assert normalizer.normalize(
        observation("start", session=InputSessionSample("g", InputSessionPhase.START, 0))
    ).event
    duplicate_start = normalizer.normalize(
        observation("start-2", session=InputSessionSample("g", InputSessionPhase.START, 1))
    )
    assert duplicate_start.reason is InputRejectionReason.SESSION_ALREADY_EXISTS
    out_of_order = normalizer.normalize(
        observation("old", session=InputSessionSample("g", InputSessionPhase.UPDATE, 0))
    )
    assert out_of_order.reason is InputRejectionReason.SESSION_SEQUENCE_OUT_OF_ORDER
    assert normalizer.normalize(
        observation("end", session=InputSessionSample("g", InputSessionPhase.END, 2))
    ).event
    terminal = normalizer.normalize(
        observation("late", session=InputSessionSample("g", InputSessionPhase.UPDATE, 3))
    )
    assert terminal.reason is InputRejectionReason.SESSION_TERMINATED


def test_touch_event_keeps_pointer_and_actual_contact_separate() -> None:
    touch = InputObservation(
        "touch-1",
        source(),
        InputModality.TOUCH,
        "contact_sample",
        NOW + timedelta(milliseconds=10),
        "trace-touch",
        RevisionVector(4),
        {},
        session=InputSessionSample("gesture", InputSessionPhase.START, 0),
        pointer=PointerSample(0.1, 0.8, pressure=0.4),
        contact=ContactPercept(
            ContactTargetKind.YURA_BODY,
            0.9,
            "avatar-hit-test",
            5,
            body_region="head",
        ),
    )
    result = InputNormalizer().normalize(touch)
    assert result.event is not None
    assert result.event.pointer is not None
    assert result.event.contact is not None
    payload = cast(Mapping[str, object], result.event.envelope.payload)
    contact = cast(Mapping[str, object], payload["contact"])
    assert contact["body_region"] == "head"
