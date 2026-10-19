"""#359のstorage-neutralな永続化DTOとfailure境界。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from math import isfinite
from typing import TypeAlias

from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    require_revision,
    thaw_json,
)
from app.domain.contracts.persistence import DurabilityReceipt as DurabilityReceipt
from app.domain.contracts.persistence import DurabilityStatus as DurabilityStatus
from app.domain.contracts.persistence import PersistenceError as PersistenceError
from app.domain.contracts.persistence import PersistenceFailureCode as PersistenceFailureCode


class PersistenceAvailability(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    CLOSED = "closed"


class IntegrityStatus(str, Enum):
    VALID = "valid"
    INTEGRITY_FAILED = "integrity_failed"


def _identifiers(values: object, name: str, *, maximum: int = 64) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{name}が配列ではありません")
    result = tuple(values)
    if (
        len(result) > maximum
        or any(not isinstance(value, str) or not value.strip() for value in result)
        or len(set(result)) != len(result)
    ):
        raise ValueError(f"{name}が不正です")
    return result


def _bounded_json(value: object, name: str, *, depth: int = 0) -> JsonValue:
    if depth > 12:
        raise ValueError(f"{name}が許容depthを超えています")
    if value is None or type(value) in {bool, int, float, str}:
        if isinstance(value, float) and not isfinite(value):
            raise ValueError(f"{name}に有限でない数値を含められません")
        if isinstance(value, str) and len(value) > 8_192:
            raise ValueError(f"{name}の文字列が長すぎます")
    elif isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError(f"{name}のobjectが大きすぎます")
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ValueError(f"{name}のkeyが不正です")
            _bounded_json(child, name, depth=depth + 1)
    elif isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise ValueError(f"{name}のarrayが大きすぎます")
        for child in value:
            _bounded_json(child, name, depth=depth + 1)
    else:
        raise ValueError(f"{name}のJSON値が不正です")
    try:
        return freeze_json(value)
    except RecursionError as error:
        raise ValueError(f"{name}が許容depthを超えています") from error


def canonical_json(value: JsonValue) -> str:
    return json.dumps(
        thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def snapshot_digest(
    *,
    snapshot_id: str,
    owner_id: str,
    snapshot_kind: str,
    snapshot_schema_id: str,
    snapshot_schema_version: int,
    owner_state_revision: int,
    runtime_epoch: str,
    captured_at: datetime,
    payload: JsonValue,
    source_refs: tuple[str, ...],
) -> str:
    material = {
        "snapshot_id": snapshot_id,
        "captured_at": captured_at.isoformat(),
        "owner_id": owner_id,
        "snapshot_kind": snapshot_kind,
        "snapshot_schema_id": snapshot_schema_id,
        "snapshot_schema_version": snapshot_schema_version,
        "owner_state_revision": owner_state_revision,
        "runtime_epoch": runtime_epoch,
        "payload": thaw_json(payload),
        "source_refs": list(source_refs),
    }
    return sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PersistenceSnapshotEnvelope:
    snapshot_id: str
    owner_id: str
    snapshot_kind: str
    snapshot_schema_id: str
    snapshot_schema_version: int
    owner_state_revision: int
    runtime_epoch: str
    captured_at: datetime
    payload: JsonValue
    payload_digest: str = ""
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id",
            "owner_id",
            "snapshot_kind",
            "snapshot_schema_id",
            "runtime_epoch",
        ):
            require_identifier(getattr(self, name), name)
        require_revision(self.snapshot_schema_version, "snapshot_schema_version")
        require_revision(self.owner_state_revision, "owner_state_revision")
        require_aware(self.captured_at, "captured_at")
        payload = _bounded_json(self.payload, "payload")
        object.__setattr__(self, "payload", payload)
        refs = _identifiers(self.source_refs, "source_refs")
        object.__setattr__(self, "source_refs", refs)
        expected = snapshot_digest(
            snapshot_id=self.snapshot_id,
            captured_at=self.captured_at,
            owner_id=self.owner_id,
            snapshot_kind=self.snapshot_kind,
            snapshot_schema_id=self.snapshot_schema_id,
            snapshot_schema_version=self.snapshot_schema_version,
            owner_state_revision=self.owner_state_revision,
            runtime_epoch=self.runtime_epoch,
            payload=payload,
            source_refs=refs,
        )
        if not self.payload_digest:
            object.__setattr__(self, "payload_digest", expected)
        elif self.payload_digest != expected:
            raise ValueError("payload_digestがpayloadまたはidentityと一致しません")

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "owner_id": self.owner_id,
            "snapshot_kind": self.snapshot_kind,
            "snapshot_schema_id": self.snapshot_schema_id,
            "snapshot_schema_version": self.snapshot_schema_version,
            "owner_state_revision": self.owner_state_revision,
            "runtime_epoch": self.runtime_epoch,
            "captured_at": self.captured_at.isoformat(),
            "payload": thaw_json(self.payload),
            "payload_digest": self.payload_digest,
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True, slots=True)
class RehydrationCandidate:
    snapshot_ref: str
    owner_id: str
    snapshot_kind: str
    snapshot_schema_id: str
    snapshot_schema_version: int
    owner_state_revision: int
    runtime_epoch: str
    captured_at: datetime
    decoded_payload: JsonValue
    integrity_status: IntegrityStatus
    storage_version: int

    def __post_init__(self) -> None:
        for name in (
            "snapshot_ref",
            "owner_id",
            "snapshot_kind",
            "snapshot_schema_id",
            "runtime_epoch",
        ):
            require_identifier(getattr(self, name), name)
        require_revision(self.snapshot_schema_version, "snapshot_schema_version")
        require_revision(self.owner_state_revision, "owner_state_revision")
        require_revision(self.storage_version, "storage_version")
        require_aware(self.captured_at, "captured_at")
        if not isinstance(self.integrity_status, IntegrityStatus):
            raise ValueError("integrity_statusが不正です")
        object.__setattr__(
            self,
            "decoded_payload",
            _bounded_json(self.decoded_payload, "decoded_payload"),
        )


SnapshotPayload: TypeAlias = Mapping[str, JsonValue] | tuple[JsonValue, ...]
