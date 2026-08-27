"""Bounded restart-safe checkpoint codec for Loop Engineering health state."""

from __future__ import annotations

import json
from typing import cast

from .models import LoopHealthEvent, LoopHealthKind

_VERSION = 1
_MAX_EVENTS = 256
_MAX_AFFECTED_WORKS = 32
_MAX_SOURCE_REFS = 32
_MAX_TEXT = 160
_MAX_OCCURRENCES = 1_000_000


def encode_health_state(events: tuple[LoopHealthEvent, ...]) -> str:
    if len(events) > _MAX_EVENTS:
        raise ValueError("too many loop health events")
    payload = {
        "version": _VERSION,
        "events": [_encode_event(event) for event in events],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_health_state(raw: str) -> tuple[LoopHealthEvent, ...]:
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("loop health state must be an object")
    payload = cast(dict[object, object], value)
    if payload.get("version") != _VERSION:
        raise ValueError("unsupported loop health state version")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or len(raw_events) > _MAX_EVENTS:
        raise ValueError("invalid loop health events")
    return tuple(_decode_event(item) for item in raw_events)


def _encode_event(event: LoopHealthEvent) -> dict[str, object]:
    _validate_event(event)
    return {
        "kind": event.kind.value,
        "fingerprint": event.fingerprint,
        "occurrence_count": event.occurrence_count,
        "affected_work_ids": list(event.affected_work_ids),
        "source_refs": list(event.source_refs),
        "blocked_work_count": event.blocked_work_count,
        "manual_intervention_required": event.manual_intervention_required,
    }


def _decode_event(raw: object) -> LoopHealthEvent:
    if not isinstance(raw, dict):
        raise ValueError("loop health event must be an object")
    item = cast(dict[object, object], raw)
    allowed = {
        "kind",
        "fingerprint",
        "occurrence_count",
        "affected_work_ids",
        "source_refs",
        "blocked_work_count",
        "manual_intervention_required",
    }
    if set(item) != allowed:
        raise ValueError("loop health event fields mismatch")

    kind_raw = _text(item["kind"], "kind")
    try:
        kind = LoopHealthKind(kind_raw)
    except ValueError as exc:
        raise ValueError("unknown loop health kind") from exc

    affected = _integer_tuple(item["affected_work_ids"], "affected_work_ids", _MAX_AFFECTED_WORKS)
    refs = _text_tuple(item["source_refs"], "source_refs", _MAX_SOURCE_REFS)
    event = LoopHealthEvent(
        kind=kind,
        fingerprint=_text(item["fingerprint"], "fingerprint"),
        occurrence_count=_bounded_int(
            item["occurrence_count"],
            "occurrence_count",
            minimum=1,
            maximum=_MAX_OCCURRENCES,
        ),
        affected_work_ids=affected,
        source_refs=refs,
        blocked_work_count=_bounded_int(
            item["blocked_work_count"],
            "blocked_work_count",
            minimum=0,
            maximum=_MAX_OCCURRENCES,
        ),
        manual_intervention_required=_boolean(
            item["manual_intervention_required"],
            "manual_intervention_required",
        ),
    )
    _validate_event(event)
    return event


def _validate_event(event: LoopHealthEvent) -> None:
    _text(event.fingerprint, "fingerprint")
    if not 1 <= event.occurrence_count <= _MAX_OCCURRENCES:
        raise ValueError("occurrence_count out of range")
    if not 0 <= event.blocked_work_count <= _MAX_OCCURRENCES:
        raise ValueError("blocked_work_count out of range")
    if len(event.affected_work_ids) > _MAX_AFFECTED_WORKS:
        raise ValueError("too many affected work ids")
    if len(event.source_refs) > _MAX_SOURCE_REFS:
        raise ValueError("too many source refs")
    for work_id in event.affected_work_ids:
        if isinstance(work_id, bool) or not isinstance(work_id, int) or work_id < 1:
            raise ValueError("invalid affected work id")
    for ref in event.source_refs:
        _text(ref, "source_ref")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT:
        raise ValueError(f"invalid {name}")
    return value


def _integer_tuple(value: object, name: str, limit: int) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"invalid {name}")
    result: list[int] = []
    for raw in value:
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise ValueError(f"invalid {name}")
        result.append(raw)
    return tuple(result)


def _text_tuple(value: object, name: str, limit: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"invalid {name}")
    return tuple(_text(item, name) for item in value)


def _bounded_int(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid {name}")
    if not minimum <= value <= maximum:
        raise ValueError(f"invalid {name}")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"invalid {name}")
    return value
