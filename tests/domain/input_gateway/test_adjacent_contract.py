from datetime import datetime, timezone
from typing import cast

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import CapabilityAvailability, RevisionVector
from app.domain.input_gateway import (
    InputAdmissionLedger,
    InputModality,
    InputNormalizer,
    InputObservation,
    InputPermission,
    InputSessionRegistry,
    InputSourceState,
)


def test_consumer_can_route_by_modality_without_reinterpreting_source_api() -> None:
    observation = InputObservation(
        "stream-1",
        InputSourceState(
            "streaming-chat",
            "subsystem",
            CapabilityAvailability.DEGRADED,
            InputPermission.NOT_REQUIRED,
            "stream-chat-events",
        ),
        InputModality.SUBSYSTEM,
        "chat_message",
        datetime(2026, 8, 19, tzinfo=timezone.utc),
        "trace-stream",
        RevisionVector(9),
        {"message_ref": "message-42", "author_ref": "viewer-7"},
    )
    admission = InputNormalizer(
        InputAdmissionLedger(),
        InputSessionRegistry(),
        bounds_policy=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    ).normalize(observation)
    assert admission.event is not None
    consumer_view = admission.event.to_dict()
    envelope = cast(dict[str, object], consumer_view["envelope"])
    payload = cast(dict[str, object], envelope["payload"])
    assert consumer_view["modality"] == "subsystem"
    assert payload["content"] == {
        "message_ref": "message-42",
        "author_ref": "viewer-7",
    }
    assert not any("youtube" in key for key in payload)
