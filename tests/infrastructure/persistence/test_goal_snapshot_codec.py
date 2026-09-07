"""復元候補のリビジョンと相互参照を、目標所有者の初期化境界で検査する。"""

from dataclasses import replace

import pytest

from app.domain.contracts.common import freeze_json, thaw_json
from app.domain.executive import CommitmentTransitionOperation, GoalTransitionOperation
from app.domain.goals import GoalCommitmentStore
from app.infrastructure.persistence import (
    InMemoryLifecycleSnapshotRepository,
    IntegrityStatus,
    PersistenceError,
    PersistenceFailureCode,
    RehydrationCandidate,
)
from app.infrastructure.persistence.goal_snapshot_codec import (
    decode_goal_snapshot,
    encode_goal_snapshot,
)
from tests.domain.goals.test_goal_commitment_store import (
    commitment_transition,
    decision,
    goal_transition,
)


def candidate() -> RehydrationCandidate:
    store = GoalCommitmentStore()
    current = store.apply(
        decision(
            "create",
            0,
            goals=(goal_transition(GoalTransitionOperation.CREATE, 0),),
            commitments=(commitment_transition(CommitmentTransitionOperation.CREATE, 0),),
        )
    ).snapshot
    repository = InMemoryLifecycleSnapshotRepository()
    repository.put_snapshot(encode_goal_snapshot(current, snapshot_id="saved", runtime_epoch="old"))
    result = repository.get_latest("goals", "goal_commitment")
    assert result is not None
    return result


@pytest.mark.parametrize(
    "owner,kind,schema,version",
    [
        ("goals", "goal_commitment", "goals.commitment.snapshot.v1", 2),
        ("emotion", "goal_commitment", "goals.commitment.snapshot.v1", 1),
        ("goals", "in_flight_activity", "goals.commitment.snapshot.v1", 1),
        ("goals", "goal_commitment", "unknown", 1),
    ],
)
def test_other_owners_and_unknown_payload_schemas_are_not_restored(
    owner: str,
    kind: str,
    schema: str,
    version: int,
) -> None:
    with pytest.raises(PersistenceError) as error:
        decode_goal_snapshot(
            replace(
                candidate(),
                owner_id=owner,
                snapshot_kind=kind,
                snapshot_schema_id=schema,
                snapshot_schema_version=version,
            )
        )
    assert error.value.code is PersistenceFailureCode.INCOMPATIBLE_PAYLOAD_VERSION


def test_owner_rejects_missing_references_even_with_valid_storage_candidate() -> None:
    item = candidate()
    payload = thaw_json(item.decoded_payload)
    assert isinstance(payload, dict)
    commitments = payload["commitments"]
    assert isinstance(commitments, list) and isinstance(commitments[0], dict)
    commitments[0]["related_goal_refs"] = ["absent-goal"]
    with pytest.raises(PersistenceError) as error:
        decode_goal_snapshot(replace(item, decoded_payload=freeze_json(payload)))
    assert error.value.code is PersistenceFailureCode.CORRUPT_RECORD


def test_storage_revision_must_match_owner_revision() -> None:
    with pytest.raises(PersistenceError) as error:
        decode_goal_snapshot(replace(candidate(), owner_state_revision=99))
    assert error.value.code is PersistenceFailureCode.CORRUPT_RECORD


def test_failed_integrity_candidate_is_never_rehydrated() -> None:
    with pytest.raises(PersistenceError) as error:
        decode_goal_snapshot(
            replace(candidate(), integrity_status=IntegrityStatus.INTEGRITY_FAILED)
        )
    assert error.value.code is PersistenceFailureCode.INTEGRITY_FAILED
