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
from app.infrastructure.persistence.postgresql_connection import PostgresDatabase, PostgresEndpoint
from tests.domain.goals.test_goal_commitment_store import decision, goal_transition
from tests.infrastructure.postgresql.test_memory import POLICY
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


def test_failed_restore_cannot_replace_saved_goals_after_reconnect(
    endpoint: PostgresEndpoint,
) -> None:
    async def run() -> None:
        seed = runtime(endpoint)
        try:
            assert await seed.start() is None
            original = await CoreGoalPersistenceBinding.restore(seed, runtime_epoch="seed")
            saved = original.apply(
                decision(
                    "save-A",
                    0,
                    goals=(goal_transition(GoalTransitionOperation.CREATE, 0, goal_id="goal-A"),),
                )
            )
            assert (await saved.durability).status is DurabilityStatus.DURABLE
        finally:
            await seed.close()
        interrupted = runtime(endpoint)
        blocker = PostgresDatabase.connect(endpoint, POLICY)
        try:
            assert await interrupted.start() is None
            with blocker.transaction() as connection:
                connection.execute(
                    "LOCK TABLE yura_v2.lifecycle_snapshots IN ACCESS EXCLUSIVE MODE"
                )
                provisional = await CoreGoalPersistenceBinding.restore(
                    interrupted,
                    runtime_epoch="failed-restore",
                )
                assert provisional.restore_failure is PersistenceFailureCode.TIMEOUT
                assert provisional.snapshot().revision == 0
                first = provisional.apply(
                    decision(
                        "create-B",
                        0,
                        goals=(
                            goal_transition(GoalTransitionOperation.CREATE, 0, goal_id="goal-B"),
                        ),
                    )
                )
            assert await interrupted.start() is None
            second = provisional.apply(
                decision(
                    "change-B",
                    1,
                    goals=(
                        goal_transition(GoalTransitionOperation.REPRIORITIZE, 1, goal_id="goal-B"),
                    ),
                )
            )
            assert second.committed.snapshot.revision == 2
            assert [goal.goal_id for goal in provisional.snapshot().goals] == ["goal-B"]
            first_receipt, second_receipt = await asyncio.gather(
                first.durability, second.durability
            )
            assert second_receipt.status is DurabilityStatus.FAILED
            assert first_receipt.failure_code is PersistenceFailureCode.TIMEOUT
            assert second_receipt.failure_code is PersistenceFailureCode.TIMEOUT
        finally:
            blocker.close()
            await interrupted.close()
        restarted = runtime(endpoint)
        try:
            assert await restarted.start() is None
            restored = await CoreGoalPersistenceBinding.restore(
                restarted, runtime_epoch="restarted"
            )
            assert restored.restore_failure is None
            assert restored.snapshot() == saved.committed.snapshot
            followup = restored.apply(
                decision(
                    "change-A",
                    1,
                    goals=(
                        goal_transition(GoalTransitionOperation.REPRIORITIZE, 1, goal_id="goal-A"),
                    ),
                )
            )
            assert (await followup.durability).status is DurabilityStatus.DURABLE
        finally:
            await restarted.close()

    asyncio.run(run())
