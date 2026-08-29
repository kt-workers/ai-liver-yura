"""Loop Engineering健全性状態を、上限付きかつ再起動安全にCheckpointへ保存・復元する。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import cast

from .models import LoopHealthEvent, LoopHealthKind

_VERSION = 1
_MAX_EVENTS = 256
_MAX_AFFECTED_WORKS = 32
_MAX_SOURCE_REFS = 32
_MAX_TEXT = 160
_MAX_OCCURRENCES = 1_000_000
_DURABLE_IDENTITY = re.compile(r"sha256:[0-9a-f]{24}\Z")


def encode_health_state(events: tuple[LoopHealthEvent, ...]) -> str:
    if len(events) > _MAX_EVENTS:
        raise ValueError("Loop健全性事象が上限を超えています")
    payload = {
        "version": _VERSION,
        "events": [_encode_event(event) for event in events],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_health_state(raw: str) -> tuple[LoopHealthEvent, ...]:
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Loop健全性状態はオブジェクト形式である必要があります")
    payload = cast(dict[object, object], value)
    if payload.get("version") != _VERSION:
        raise ValueError("対応していないLoop健全性状態の版です")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or len(raw_events) > _MAX_EVENTS:
        raise ValueError("Loop健全性事象が不正です")
    return tuple(_decode_event(item) for item in raw_events)


def _encode_event(event: LoopHealthEvent) -> dict[str, object]:
    event = canonicalize_event(event)
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
        raise ValueError("Loop健全性事象はオブジェクト形式である必要があります")
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
        raise ValueError("Loop健全性事象の項目構成が一致しません")

    kind_raw = _text(item["kind"], "kind")
    try:
        kind = LoopHealthKind(kind_raw)
    except ValueError as exc:
        raise ValueError("未知のLoop健全性種別です") from exc

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
    return canonicalize_event(event)


def canonicalize_event(event: LoopHealthEvent) -> LoopHealthEvent:
    """信頼できない永続文章を、不透明で再起動後も安定するidentityへ置き換える。"""
    _validate_event(event)
    return LoopHealthEvent(
        kind=event.kind,
        fingerprint=durable_identity(event.fingerprint),
        occurrence_count=event.occurrence_count,
        affected_work_ids=event.affected_work_ids,
        source_refs=tuple(durable_identity(item) for item in event.source_refs),
        blocked_work_count=event.blocked_work_count,
        manual_intervention_required=event.manual_intervention_required,
    )


def durable_identity(value: str) -> str:
    if _DURABLE_IDENTITY.fullmatch(value):
        return value
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _validate_event(event: LoopHealthEvent) -> None:
    _text(event.fingerprint, "fingerprint")
    if not 1 <= event.occurrence_count <= _MAX_OCCURRENCES:
        raise ValueError("occurrence_countが許容範囲外です")
    if not 0 <= event.blocked_work_count <= _MAX_OCCURRENCES:
        raise ValueError("blocked_work_countが許容範囲外です")
    if len(event.affected_work_ids) > _MAX_AFFECTED_WORKS:
        raise ValueError("影響Workの識別子が上限を超えています")
    if len(event.source_refs) > _MAX_SOURCE_REFS:
        raise ValueError("証拠参照が上限を超えています")
    for work_id in event.affected_work_ids:
        if isinstance(work_id, bool) or not isinstance(work_id, int) or work_id < 1:
            raise ValueError("影響Workの識別子が不正です")
    for ref in event.source_refs:
        _text(ref, "source_ref")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT:
        raise ValueError(f"{name}が不正です")
    return value


def _integer_tuple(value: object, name: str, limit: int) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{name}が不正です")
    result: list[int] = []
    for raw in value:
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise ValueError(f"{name}が不正です")
        result.append(raw)
    return tuple(result)


def _text_tuple(value: object, name: str, limit: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{name}が不正です")
    return tuple(_text(item, name) for item in value)


def _bounded_int(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name}が不正です")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name}が不正です")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name}が不正です")
    return value
