"""本体の目標変更入口から保存し、所有者検査を経て復元する。"""

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace

import pytest

from app.composition.goal_persistence import CoreGoalPersistenceBinding
from app.domain.executive import GoalTransitionOperation
from app.domain.goals import GoalCommitmentStore
from app.infrastructure.persistence import DurabilityStatus, PersistenceFailureCode
from app.infrastructure.persistence.postgresql_connection import PostgresEndpoint
from tests.domain.goals.test_goal_commitment_store import decision, goal_transition
from tests.infrastructure.postgresql.test_runtime import runtime


def test_goal_binding_persists_each_commit_and_restores_owner(endpoint: PostgresEndpoint) -> None:
    async def run() -> None:
        first = runtime(endpoint)
        try:
            assert await first.start() is None
            binding = await CoreGoalPersistenceBinding.restore(first, runtime_epoch="first")
            assert binding.restore_failure is None
            result = binding.apply(
                decision(
                    "create",
                    0,
                    goals=(goal_transition(GoalTransitionOperation.CREATE, 0),),
                )
            )
            assert binding.snapshot() == result.committed.snapshot
            receipt = await result.durability
            assert receipt.status is DurabilityStatus.DURABLE
            assert receipt.owner_state_revision == result.committed.snapshot.revision
        finally:
            await first.close()
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.infrastructure.postgresql.goal_binding_process",
                endpoint.host,
                str(endpoint.port),
                endpoint.database,
                endpoint.user,
            ],
            check=True,
            text=True,
            capture_output=True,
            timeout=15,
            env={"PATH": os.defpath, "PYTHONPATH": os.pathsep.join(sys.path)},
        )
        assert json.loads(child.stdout) == result.committed.snapshot.to_dict()
        second = runtime(endpoint)
        try:
            assert await second.start() is None
            restored = await CoreGoalPersistenceBinding.restore(second, runtime_epoch="second")
            assert restored.restore_failure is None
            assert restored.snapshot() == result.committed.snapshot
            updated = restored.apply(
                decision(
                    "reprioritize",
                    1,
                    goals=(goal_transition(GoalTransitionOperation.REPRIORITIZE, 1),),
                )
            )
            assert updated.committed.snapshot.revision == 2
            assert (await updated.durability).status is DurabilityStatus.DURABLE
        finally:
            await second.close()
        assert second.pending_task_count == 0

    asyncio.run(run())


def test_unavailable_storage_does_not_lose_committed_goal(endpoint: PostgresEndpoint) -> None:
    async def run() -> None:
        persistence = runtime(endpoint)
        try:
            binding = await CoreGoalPersistenceBinding.restore(persistence, runtime_epoch="offline")
            assert binding.restore_failure is PersistenceFailureCode.UNAVAILABLE
            result = binding.apply(
                decision(
                    "create-offline",
                    0,
                    goals=(goal_transition(GoalTransitionOperation.CREATE, 0),),
                )
            )
            assert binding.snapshot() == result.committed.snapshot
            assert binding.snapshot().revision == 1
            receipt = await result.durability
            assert receipt.status is DurabilityStatus.FAILED
            assert receipt.failure_code is PersistenceFailureCode.UNAVAILABLE
            assert receipt.owner_state_revision == 1
        finally:
            await persistence.close()

    asyncio.run(run())


def test_snapshot_format_failure_preserves_committed_state(endpoint: PostgresEndpoint) -> None:
    async def run() -> None:
        persistence = runtime(endpoint)
        try:
            assert await persistence.start() is None
            binding = await CoreGoalPersistenceBinding.restore(persistence, runtime_epoch="large")
            transition = goal_transition(GoalTransitionOperation.CREATE, 0)
            transition = replace(
                transition,
                payload=replace(
                    transition.payload,
                    semantic_goal_ref="x" * 8193,
                ),
            )
            result = binding.apply(decision("large", 0, goals=(transition,)))
            assert binding.snapshot() == result.committed.snapshot
            receipt = await result.durability
            assert receipt.failure_code is PersistenceFailureCode.CONSTRAINT_VIOLATION
            assert receipt.owner_state_revision == 1
            assert (await persistence.restore_goals()).value is None
        finally:
            await persistence.close()

    asyncio.run(run())


def test_missing_event_loop_rejects_before_goal_change(endpoint: PostgresEndpoint) -> None:
    persistence = runtime(endpoint)
    binding = CoreGoalPersistenceBinding(
        GoalCommitmentStore(),
        persistence,
        runtime_epoch="no-loop",
    )
    try:
        with pytest.raises(RuntimeError, match="running event loop"):
            binding.apply(
                decision(
                    "create-no-loop",
                    0,
                    goals=(goal_transition(GoalTransitionOperation.CREATE, 0),),
                )
            )
        assert binding.snapshot().revision == 0
    finally:
        asyncio.run(persistence.close())
