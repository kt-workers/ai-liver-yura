import json

import pytest

from tools.loop_engine.health_state import (
    canonicalize_event,
    decode_health_state,
    encode_health_state,
)
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
    assert decode_health_state(encoded) == tuple(canonicalize_event(event) for event in events)
    assert encode_health_state(decode_health_state(encoded)) == encoded


def test_health_state_redacts_raw_credential_like_evidence_before_persistence() -> None:
    raw = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
    encoded = encode_health_state(
        (LoopHealthEvent(LoopHealthKind.REPEATED_FAILURE, raw, 3, source_refs=(raw,)),)
    )
    assert raw not in encoded
    restored = decode_health_state(encoded)[0]
    assert restored.fingerprint.startswith("sha256:")
    assert restored.source_refs[0].startswith("sha256:")


def test_health_state_rejects_unknown_fields_and_kinds() -> None:
    event_payload: dict[str, object] = {
        "kind": "UNKNOWN",
        "fingerprint": "bad",
        "occurrence_count": 1,
        "affected_work_ids": [],
        "source_refs": [],
        "blocked_work_count": 0,
        "manual_intervention_required": False,
    }
    payload: dict[str, object] = {"version": 1, "events": [event_payload]}
    with pytest.raises(ValueError, match="未知のLoop健全性種別"):
        decode_health_state(json.dumps(payload))

    event_payload["kind"] = "NO_PROGRESS"
    event_payload["unexpected"] = "data"
    with pytest.raises(ValueError, match="項目構成が一致しません"):
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
    with pytest.raises(ValueError, match="上限を超えています"):
        encode_health_state(too_many)
