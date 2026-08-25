"""#332 Memory recordをsafe JSONへ限定するcodec。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from typing import cast

from app.domain.contracts.common import freeze_json
from app.domain.memory.contracts import (
    MemoryConfidence,
    MemoryContent,
    MemoryFreshnessState,
    MemoryKind,
    MemoryLifecycle,
    MemoryProvenance,
    MemoryRecord,
    MemorySourceKind,
    MemoryTemporalState,
)

from .contracts import PersistenceError, PersistenceFailureCode


def encode_memory_record(record: MemoryRecord) -> str:
    if not isinstance(record, MemoryRecord):
        raise ValueError("recordが不正です")
    return json.dumps(
        {
            "memory_id": record.memory_id,
            "revision": record.revision,
            "kind": record.kind.value,
            "content": record.content.to_dict(),
            "provenance": [item.to_dict() for item in record.provenance],
            "confidence": {"value": record.confidence.value, "basis": record.confidence.basis},
            "temporal": _temporal_to_json(record.temporal),
            "lifecycle": record.lifecycle.value,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def decode_memory_record(raw: str) -> MemoryRecord:
    try:
        value = _mapping(json.loads(raw))
        content = _mapping(value["content"])
        confidence = _mapping(value["confidence"])
        return MemoryRecord(
            _text(value, "memory_id"),
            _integer(value, "revision"),
            MemoryKind(_text(value, "kind")),
            MemoryContent(
                _text(content, "predicate"),
                freeze_json(content["value"]),
                _optional_text(content, "subject_ref"),
                _optional_text(content, "temporal_scope_ref"),
                _texts(content, "qualifiers"),
            ),
            _provenance(value),
            MemoryConfidence(_number(confidence, "value"), _text(confidence, "basis")),
            _temporal_from_json(_mapping(value["temporal"])),
            MemoryLifecycle(_text(value, "lifecycle")),
            _instant(value, "created_at"),
            _instant(value, "updated_at"),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PersistenceError(
            PersistenceFailureCode.CORRUPT_RECORD,
            "Memory recordが不正です",
        ) from error


def _temporal_to_json(temporal: MemoryTemporalState) -> dict[str, object]:
    return {
        "freshness": temporal.freshness.value,
        "valid_from": _timestamp(temporal.valid_from),
        "valid_until": _timestamp(temporal.valid_until),
        "observed_at": _timestamp(temporal.observed_at),
    }


def _temporal_from_json(value: Mapping[str, object]) -> MemoryTemporalState:
    return MemoryTemporalState(
        MemoryFreshnessState(_text(value, "freshness")),
        _optional_instant(value, "valid_from"),
        _optional_instant(value, "valid_until"),
        _optional_instant(value, "observed_at"),
    )


def _provenance(value: Mapping[str, object]) -> tuple[MemoryProvenance, ...]:
    items = value["provenance"]
    if not isinstance(items, list):
        raise ValueError("provenanceが不正です")
    return tuple(
        MemoryProvenance(
            MemorySourceKind(_text(item, "source_kind")),
            _texts(item, "source_event_refs"),
            _texts(item, "source_fact_refs"),
            _optional_text(item, "source_memory_candidate_id"),
            _optional_instant(item, "observed_at"),
            _instant(item, "recorded_at"),
        )
        for item in (_mapping(item) for item in items)
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("mappingが不正です")
    return cast(Mapping[str, object], value)


def _text(value: Mapping[str, object], name: str) -> str:
    result = value[name]
    if not isinstance(result, str):
        raise ValueError(f"{name}が不正です")
    return result


def _optional_text(value: Mapping[str, object], name: str) -> str | None:
    result = value[name]
    if result is not None and not isinstance(result, str):
        raise ValueError(f"{name}が不正です")
    return result


def _texts(value: Mapping[str, object], name: str) -> tuple[str, ...]:
    result = value[name]
    if not isinstance(result, list) or any(not isinstance(item, str) for item in result):
        raise ValueError(f"{name}が不正です")
    return tuple(result)


def _integer(value: Mapping[str, object], name: str) -> int:
    result = value[name]
    if type(result) is not int:
        raise ValueError(f"{name}が不正です")
    return result


def _number(value: Mapping[str, object], name: str) -> float:
    result = value[name]
    if type(result) not in {int, float}:
        raise ValueError(f"{name}が不正です")
    numeric = float(cast(int | float, result))
    if not isfinite(numeric):
        raise ValueError(f"{name}が不正です")
    return numeric


def _timestamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _instant(value: Mapping[str, object], name: str) -> datetime:
    result = _text(value, name)
    parsed = datetime.fromisoformat(result)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name}が不正です")
    return parsed


def _optional_instant(value: Mapping[str, object], name: str) -> datetime | None:
    if value[name] is None:
        return None
    return _instant(value, name)
