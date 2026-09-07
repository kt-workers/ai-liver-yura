from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    BrainOperationalBoundsPolicy,
)
from app.domain.contracts import CapabilityAvailability, RevisionVector
from app.domain.contracts.common import JsonValue
from app.domain.input_gateway import (
    ContactPercept,
    ContactTargetKind,
    InputAdmissionLedger,
    InputAdmissionStatus,
    InputModality,
    InputNormalizer,
    InputObservation,
    InputPermission,
    InputRejectionReason,
    InputSessionPhase,
    InputSessionRegistry,
    InputSessionSample,
    InputSourceLifecycleChange,
    InputSourceState,
    PointerSample,
)

NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)


def normalizer(
    policy: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
) -> InputNormalizer:
    return InputNormalizer(
        InputAdmissionLedger(),
        InputSessionRegistry(),
        bounds_policy=policy,
    )


def policy_with_input(**changes: int) -> BrainOperationalBoundsPolicy:
    return replace(
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        input=replace(V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.input, **changes),
    )


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
    payload: JsonValue | None = None,
) -> InputObservation:
    return InputObservation(
        observation_id,
        input_source or source(),
        modality,
        "utterance",
        NOW,
        "trace-1",
        RevisionVector(3, goal_revision=2),
        cast(JsonValue, {"text": "こんにちは"}) if payload is None else payload,
        correlation_id="conversation-1",
        session=session,
    )


def test_normalizes_source_neutral_foundation_event_without_meaning() -> None:
    result = normalizer().normalize(observation("obs-1"))
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
    gateway = normalizer()
    unavailable = observation(
        "same",
        input_source=source(availability=CapabilityAvailability.UNAVAILABLE),
    )
    first = gateway.normalize(unavailable)
    second = gateway.normalize(observation("same"))
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
    result = normalizer().normalize(observation("obs", input_source=input_source))
    assert result.status is InputAdmissionStatus.REJECTED
    assert result.reason is reason


def test_lifecycle_event_reports_unavailable_source_without_fabricating_input() -> None:
    unavailable = source(
        availability=CapabilityAvailability.UNAVAILABLE,
        permission=InputPermission.DENIED,
    )
    lifecycle = InputObservation(
        "source-state",
        unavailable,
        InputModality.LIFECYCLE,
        "source_state_changed",
        NOW,
        "trace-source",
        RevisionVector(3),
        {},
        lifecycle_change=InputSourceLifecycleChange(
            CapabilityAvailability.AVAILABLE,
            InputPermission.GRANTED,
            "adapter_disconnected",
        ),
    )
    result = normalizer().normalize(lifecycle)
    assert result.event is not None
    assert result.event.envelope.event_type == "input.lifecycle.source_state_changed"
    assert result.event.source.availability is CapabilityAvailability.UNAVAILABLE


def test_continuous_session_accepts_strict_lifecycle() -> None:
    gateway = normalizer()
    phases = [
        InputSessionSample("gesture", InputSessionPhase.START, 0),
        InputSessionSample("gesture", InputSessionPhase.UPDATE, 1),
        InputSessionSample("gesture", InputSessionPhase.UPDATE, 3),
        InputSessionSample("gesture", InputSessionPhase.END, 4),
    ]
    for index, sample in enumerate(phases):
        result = gateway.normalize(observation(f"obs-{index}", session=sample))
        assert result.status is InputAdmissionStatus.ACCEPTED


def test_session_rejects_missing_duplicate_out_of_order_and_terminal_samples() -> None:
    gateway = normalizer()
    missing = gateway.normalize(
        observation("missing", session=InputSessionSample("g", InputSessionPhase.UPDATE, 1))
    )
    assert missing.reason is InputRejectionReason.SESSION_NOT_ACTIVE

    assert gateway.normalize(
        observation("start", session=InputSessionSample("g", InputSessionPhase.START, 0))
    ).event
    duplicate_start = gateway.normalize(
        observation("start-2", session=InputSessionSample("g", InputSessionPhase.START, 1))
    )
    assert duplicate_start.reason is InputRejectionReason.SESSION_ALREADY_EXISTS
    out_of_order = gateway.normalize(
        observation("old", session=InputSessionSample("g", InputSessionPhase.UPDATE, 0))
    )
    assert out_of_order.reason is InputRejectionReason.SESSION_SEQUENCE_OUT_OF_ORDER
    assert gateway.normalize(
        observation("end", session=InputSessionSample("g", InputSessionPhase.END, 2))
    ).event
    terminal = gateway.normalize(
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
    result = normalizer().normalize(touch)
    assert result.event is not None
    assert result.event.pointer is not None
    assert result.event.contact is not None
    payload = cast(Mapping[str, object], result.event.envelope.payload)
    contact = cast(Mapping[str, object], payload["contact"])
    assert contact["body_region"] == "head"


def test_lifecycle_contract_cannot_bypass_source_gate_or_mutate_session() -> None:
    unavailable = source(
        availability=CapabilityAvailability.UNAVAILABLE,
        permission=InputPermission.DENIED,
    )
    with pytest.raises(ValueError):
        InputObservation(
            "forged-lifecycle",
            unavailable,
            InputModality.LIFECYCLE,
            "utterance",
            NOW,
            "trace",
            RevisionVector(1),
            {"text": "secret observation"},
            session=InputSessionSample("forged", InputSessionPhase.START, 0),
        )


def test_shared_ledger_prevents_duplicate_across_normalizer_instances() -> None:
    ledger = InputAdmissionLedger()
    sessions = InputSessionRegistry()
    first = InputNormalizer(ledger, sessions, bounds_policy=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    second = InputNormalizer(ledger, sessions, bounds_policy=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    assert first.normalize(observation("process-unique")).event is not None
    duplicate = second.normalize(observation("process-unique"))
    assert duplicate.status is InputAdmissionStatus.DUPLICATE


def test_shared_session_registry_preserves_lifecycle_across_normalizer_instances() -> None:
    ledger = InputAdmissionLedger()
    sessions = InputSessionRegistry()
    first = InputNormalizer(ledger, sessions, bounds_policy=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    second = InputNormalizer(ledger, sessions, bounds_policy=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    start = observation(
        "shared-start",
        session=InputSessionSample("shared-session", InputSessionPhase.START, 0),
    )
    update = observation(
        "shared-update",
        session=InputSessionSample("shared-session", InputSessionPhase.UPDATE, 1),
    )
    assert first.normalize(start).event is not None
    assert second.normalize(update).event is not None


@pytest.mark.parametrize(
    ("length", "expected_reason"),
    [
        (4, None),
        (5, None),
        (6, InputRejectionReason.INPUT_TEXT_TOO_LARGE),
    ],
)
def test_text_codepoint_bound_is_exact(
    length: int, expected_reason: InputRejectionReason | None
) -> None:
    gateway = normalizer(
        policy_with_input(max_text_codepoints=5, max_payload_json_bytes=1024)
    )
    result = gateway.normalize(
        observation(f"text-{length}", payload=cast(JsonValue, {"text": "あ" * length}))
    )
    assert result.reason is expected_reason
    if expected_reason is None:
        assert result.event is not None


def test_payload_bound_uses_canonical_utf8_bytes_without_truncation() -> None:
    payload: JsonValue = {"text": "あ"}
    exact_size = len(
        json.dumps(
            {"text": "あ"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    accepted = normalizer(
        policy_with_input(max_text_codepoints=100, max_payload_json_bytes=exact_size)
    ).normalize(observation("payload-equal", payload=payload))
    rejected = normalizer(
        policy_with_input(max_text_codepoints=100, max_payload_json_bytes=exact_size)
    ).normalize(
        observation("payload-over", payload=cast(JsonValue, {"text": "ああ"}))
    )
    assert accepted.event is not None
    assert rejected.reason is InputRejectionReason.INPUT_PAYLOAD_TOO_LARGE


def test_session_metadata_bound_rejects_without_mutating_session() -> None:
    sample = InputSessionSample("gesture-long", InputSessionPhase.START, 0)
    exact_size = len(
        json.dumps(
            sample.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    policy = policy_with_input(max_session_metadata_json_bytes=exact_size - 1)
    result = normalizer(policy).normalize(observation("session-too-large", session=sample))
    assert result.reason is InputRejectionReason.INPUT_SESSION_METADATA_TOO_LARGE


def test_active_session_limit_backpressures_new_start_and_keeps_existing_session() -> None:
    gateway = normalizer(policy_with_input(max_active_sessions_per_source=1))
    first = InputSessionSample("session-1", InputSessionPhase.START, 0)
    second = InputSessionSample("session-2", InputSessionPhase.START, 0)
    assert gateway.normalize(observation("first-start", session=first)).event is not None
    blocked = gateway.normalize(observation("second-start", session=second))
    assert blocked.reason is InputRejectionReason.ACTIVE_SESSION_LIMIT_REACHED
    update = gateway.normalize(
        observation(
            "first-update",
            session=InputSessionSample("session-1", InputSessionPhase.UPDATE, 1),
        )
    )
    assert update.event is not None
