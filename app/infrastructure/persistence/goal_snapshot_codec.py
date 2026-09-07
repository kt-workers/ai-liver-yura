"""目標所有者の既存状態型と保存用JSONを、意味を変更せず対応付ける。"""

from collections.abc import Mapping
from datetime import datetime

from app.domain.contracts.common import JsonValue, freeze_json
from app.domain.goals.contracts import (
    CommitmentState,
    CommitmentStatus,
    GoalCommitmentSnapshot,
    GoalKind,
    GoalState,
    GoalStatus,
    InterruptionPolicy,
)
from app.domain.goals.store import GoalCommitmentStore

from .contracts import (
    IntegrityStatus,
    PersistenceError,
    PersistenceFailureCode,
    PersistenceSnapshotEnvelope,
    RehydrationCandidate,
)

OWNER_ID = "goals"
SNAPSHOT_KIND = "goal_commitment"
SCHEMA_ID = "goals.commitment.snapshot.v1"
SCHEMA_VERSION = 1


def encode_goal_snapshot(
    snapshot: GoalCommitmentSnapshot,
    *,
    snapshot_id: str,
    runtime_epoch: str,
) -> PersistenceSnapshotEnvelope:
    return PersistenceSnapshotEnvelope(
        snapshot_id,
        OWNER_ID,
        SNAPSHOT_KIND,
        SCHEMA_ID,
        SCHEMA_VERSION,
        snapshot.revision,
        runtime_epoch,
        snapshot.updated_at,
        freeze_json(snapshot.to_dict()),
    )


def decode_goal_snapshot(candidate: RehydrationCandidate) -> GoalCommitmentSnapshot:
    if candidate.integrity_status is not IntegrityStatus.VALID:
        raise PersistenceError(
            PersistenceFailureCode.INTEGRITY_FAILED, "整合性を確認できない状態は復元できません"
        )
    if (
        candidate.owner_id,
        candidate.snapshot_kind,
        candidate.snapshot_schema_id,
        candidate.snapshot_schema_version,
    ) != (OWNER_ID, SNAPSHOT_KIND, SCHEMA_ID, SCHEMA_VERSION):
        raise PersistenceError(
            PersistenceFailureCode.INCOMPATIBLE_PAYLOAD_VERSION,
            "目標所有者が復元できる状態形式ではありません",
        )
    try:
        data = _mapping(candidate.decoded_payload, "revision goals commitments updated_at")
        result = GoalCommitmentSnapshot(
            _integer(data["revision"]),
            tuple(_goal(item) for item in _sequence(data["goals"])),
            tuple(_commitment(item) for item in _sequence(data["commitments"])),
            _time(data["updated_at"]),
        )
        if result.revision != candidate.owner_state_revision or (
            result.updated_at != candidate.captured_at
        ):
            raise ValueError
        # 相互参照の合法性も既存所有者の初期化検査へ委譲する。
        GoalCommitmentStore(result)
        return result
    except (KeyError, TypeError, ValueError, OverflowError):
        raise PersistenceError(
            PersistenceFailureCode.CORRUPT_RECORD, "目標状態の内容または参照が不正です"
        ) from None


def _goal(value: JsonValue) -> GoalState:
    data = _mapping(
        value,
        "goal_id kind semantic_goal_ref target_ref created_from_decision_id "
        "status priority motivation_refs commitment_refs precondition_ids "
        "completion_condition_refs interruption_policy created_at updated_at revision",
    )
    return GoalState(
        _text(data["goal_id"]),
        GoalKind(_text(data["kind"])),
        _text(data["semantic_goal_ref"]),
        _optional_text(data["target_ref"]),
        _text(data["created_from_decision_id"]),
        GoalStatus(_text(data["status"])),
        _integer(data["priority"]),
        _ids(data["motivation_refs"]),
        _ids(data["commitment_refs"]),
        _ids(data["precondition_ids"]),
        _ids(data["completion_condition_refs"]),
        InterruptionPolicy(_text(data["interruption_policy"])),
        _time(data["created_at"]),
        _time(data["updated_at"]),
        _integer(data["revision"]),
    )


def _commitment(value: JsonValue) -> CommitmentState:
    data = _mapping(
        value,
        "commitment_id semantic_commitment_ref counterparty_ref "
        "source_event_ids source_decision_id related_goal_refs status strength "
        "priority due_condition_refs release_condition_refs created_at updated_at revision",
    )
    return CommitmentState(
        _text(data["commitment_id"]),
        _text(data["semantic_commitment_ref"]),
        _optional_text(data["counterparty_ref"]),
        _ids(data["source_event_ids"]),
        _text(data["source_decision_id"]),
        _ids(data["related_goal_refs"]),
        CommitmentStatus(_text(data["status"])),
        _integer(data["strength"]),
        _integer(data["priority"]),
        _ids(data["due_condition_refs"]),
        _ids(data["release_condition_refs"]),
        _time(data["created_at"]),
        _time(data["updated_at"]),
        _integer(data["revision"]),
    )


def _mapping(value: JsonValue, fields: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping) or set(value) != set(fields.split()):
        raise ValueError
    return value


def _sequence(value: JsonValue) -> tuple[JsonValue, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError
    return tuple(value)


def _text(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise ValueError
    return value


def _optional_text(value: JsonValue) -> str | None:
    return None if value is None else _text(value)


def _integer(value: JsonValue) -> int:
    if type(value) is not int:
        raise ValueError
    return value


def _ids(value: JsonValue) -> tuple[str, ...]:
    return tuple(_text(item) for item in _sequence(value))


def _time(value: JsonValue) -> datetime:
    return datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
