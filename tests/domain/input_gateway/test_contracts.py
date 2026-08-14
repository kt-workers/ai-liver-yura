from collections.abc import Mapping
from datetime import datetime, timezone
from typing import cast

import pytest

from app.domain.contracts import CapabilityAvailability, RevisionVector
from app.domain.contracts.common import JsonValue
from app.domain.input_gateway import (
    ContactPercept,
    ContactTargetKind,
    InputModality,
    InputObservation,
    InputPermission,
    InputSessionPhase,
    InputSessionSample,
    InputSourceState,
    PointerSample,
)

NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)


def source() -> InputSourceState:
    return InputSourceState(
        "gui-1",
        "gui",
        CapabilityAvailability.AVAILABLE,
        InputPermission.GRANTED,
        "cap-input-gui",
    )


def test_observation_freezes_nested_payload_and_owns_session_snapshot() -> None:
    nested_parts = ["hello"]
    nested: dict[str, object] = {"parts": nested_parts}
    observation = InputObservation(
        "obs-1",
        source(),
        InputModality.TEXT,
        "utterance",
        NOW,
        "trace-1",
        RevisionVector(2),
        cast(JsonValue, nested),
        session=InputSessionSample("turn-1", InputSessionPhase.START, 0),
    )
    nested_parts.append("mutated")
    payload = cast(Mapping[str, object], observation.payload)
    assert payload["parts"] == ("hello",)


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan")])
def test_pointer_rejects_invalid_normalized_coordinates(value: float) -> None:
    with pytest.raises(ValueError):
        PointerSample(value, 0.5)


def test_contact_requires_actual_body_region_for_yura_hit() -> None:
    with pytest.raises(ValueError):
        ContactPercept(ContactTargetKind.YURA_BODY, 0.8, "vision", 1)

    percept = ContactPercept(
        ContactTargetKind.YURA_BODY,
        0.8,
        "vision",
        1,
        body_region="left_hand",
    )
    assert percept.body_region == "left_hand"

    with pytest.raises(ValueError):
        ContactPercept(
            ContactTargetKind.ENVIRONMENT,
            0.8,
            "vision",
            1,
            body_region="head",
        )


def test_pointer_coordinates_do_not_imply_contact() -> None:
    observation = InputObservation(
        "obs-pointer",
        source(),
        InputModality.POINTER,
        "sample",
        NOW,
        "trace-1",
        RevisionVector(0),
        {},
        pointer=PointerSample(0.2, 0.7),
    )
    assert observation.pointer is not None
    assert observation.contact is None


def test_non_pointer_modality_cannot_carry_pointer_or_contact() -> None:
    with pytest.raises(ValueError):
        InputObservation(
            "obs-invalid",
            source(),
            InputModality.TEXT,
            "utterance",
            NOW,
            "trace-1",
            RevisionVector(0),
            {},
            pointer=PointerSample(0.2, 0.7),
        )
