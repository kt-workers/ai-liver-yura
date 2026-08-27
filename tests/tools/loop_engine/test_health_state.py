import json

import pytest

from tools.loop_engine.health_state import decode_health_state, encode_health_state
from tools.loop_engine.models import LoopHealthEvent, LoopHealthKind


def test_health_state_round_trip_is_restart_safe() -> None:
    events = (
        LoopHealthEvent(
            LoopHealthKind.MANUAL_OPERATION_REPEAT,
            "manual:review-copy",
            2,
            (465,),
            ("checkpoint:543",),
        ),
    )
    encoded = encode_health_state(events)
    assert decode_health_state(encoded) == events
    assert encode_health_state(decode_health_state(encoded)) == encoded


def test_health_state_rejects_unknown_fields_and_kinds() -> None:
    payload = {
        "version": 1,
        "events": [
            {
                "kind": "UNKNOWN",
                "fingerprint": "bad",
                "occurrence_count": 1,
                "affected_work_ids": [],
                "source_refs": [],
                "blocked_work_count": 0,
                "manual_intervention_required": False,
            }
        ],
    }
    with pytest.raises(ValueError, match="unknown loop health kind"):
        decode_health_state(json.dumps(payload))

    payload["events"][0]["kind"] = "NO_PROGRESS"
    payload["events"][0]["unexpected"] = "data"
    with pytest.raises(ValueError, match="fields mismatch"):
        decode_health_state(json.dumps(payload))


def test_health_state_is_bounded() -> None:
    oversized = "x" * 161
    with pytest.raises(ValueError, match="fingerprint"):
        encode_health_state(
            (LoopHealthEvent(LoopHealthKind.NO_PROGRESS, oversized, 2),)
        )

    too_many = tuple(
        LoopHealthEvent(LoopHealthKind.NO_PROGRESS, f"state-{index}", 2)
        for index in range(257)
    )
    with pytest.raises(ValueError, match="too many"):
        encode_health_state(too_many)
