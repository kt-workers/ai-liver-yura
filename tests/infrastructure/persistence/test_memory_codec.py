from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.domain.memory.contracts import (
    MemoryConfidence,
    MemoryContent,
    MemoryFreshnessState,
    MemoryKind,
    MemoryLifecycle,
    MemoryProvenance,
    MemoryRecord,
    MemoryRelation,
    MemoryRelationKind,
    MemorySourceKind,
    MemoryTemporalState,
)
from app.infrastructure.persistence.contracts import PersistenceError, PersistenceFailureCode
from app.infrastructure.persistence.memory_codec import decode_memory_record, encode_memory_record
from app.infrastructure.persistence.sqlite_memory import SqliteMemoryRepository

NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def record() -> MemoryRecord:
    return MemoryRecord(
        "memory-1",
        0,
        MemoryKind.EPISODIC,
        MemoryContent("episode", {"nested": ("safe",)}, "user-1"),
        (
            MemoryProvenance(
                MemorySourceKind.TYPED_EVENT,
                ("event-1",),
                (),
                "candidate-1",
                NOW,
                NOW,
            ),
        ),
        MemoryConfidence(0.8, "trusted"),
        MemoryTemporalState(MemoryFreshnessState.HISTORICAL, observed_at=NOW),
        MemoryLifecycle.ACTIVE,
        NOW,
        NOW,
    )


def test_memory_record_codec_round_trips_complete_canonical_metadata() -> None:
    encoded = encode_memory_record(record())
    decoded = decode_memory_record(encoded)

    assert decoded == record()
    assert "pickle" not in encoded


def test_memory_record_codec_fails_closed_for_corrupt_payload() -> None:
    with pytest.raises(PersistenceError) as raised:
        decode_memory_record('{"memory_id":"memory-1"}')

    assert raised.value.code is PersistenceFailureCode.CORRUPT_RECORD


def test_memory_record_codec_rejects_non_finite_confidence() -> None:
    encoded = encode_memory_record(record()).replace('"value":0.8', '"value":NaN')

    with pytest.raises(PersistenceError) as raised:
        decode_memory_record(encoded)

    assert raised.value.code is PersistenceFailureCode.CORRUPT_RECORD


def test_sqlite_memory_record_is_revision_fenced_and_survives_restart(tmp_path: Path) -> None:
    path = str(tmp_path / "memory.sqlite")
    repository = SqliteMemoryRepository(path)

    assert repository.save_record(record(), expected_revision=None)
    assert not repository.save_record(record(), expected_revision=None)
    repository.close()

    restored = SqliteMemoryRepository(path)
    assert restored.get("memory-1") == record()
    restored.close()


def test_related_write_is_atomic_and_requires_all_relation_targets(tmp_path: Path) -> None:
    repository = SqliteMemoryRepository(str(tmp_path / "memory.sqlite"))
    current = record()
    candidate = replace(record(), memory_id="memory-2")
    relation = MemoryRelation(
        "relation-1",
        "memory-2",
        "memory-1",
        MemoryRelationKind.REFINES,
        ("event-1",),
        NOW,
    )
    target_update = replace(current, revision=1)

    assert repository.save_record(current, expected_revision=None)
    assert repository.commit_related(
        candidate,
        relation,
        target_update=target_update,
        expected_target_revision=0,
    )
    assert repository.get("memory-1") == target_update
    assert repository.get("memory-2") == candidate
    assert repository.list_relations() == (relation,)

    invalid = replace(candidate, memory_id="memory-3")
    invalid_relation = replace(relation, relation_id="relation-2", left_memory_id="missing")
    assert not repository.commit_related(
        invalid,
        invalid_relation,
        target_update=None,
        expected_target_revision=None,
    )
    assert repository.get("memory-3") is None
    repository.close()
