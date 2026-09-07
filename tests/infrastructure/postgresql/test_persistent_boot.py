"""保存済み状態を本体の参照入口へ接続し、起動と停止の資源を回収する。"""

import asyncio
from pathlib import Path

import pytest
import yaml

from app.bootstrap import build_persistent_core
from app.composition.goal_persistence import CoreGoalPersistenceBinding
from app.domain.executive import GoalTransitionOperation
from app.domain.goals import GoalCommitmentSnapshot
from app.domain.memory import MemoryWriteRequest
from app.infrastructure.persistence import (
    DurabilityStatus,
    PersistenceAvailability,
    PersistenceFailureCode,
    PersistenceOperationResult,
    PostgresPersistenceRuntime,
)
from app.infrastructure.persistence.postgresql_connection import PostgresDatabase, PostgresEndpoint
from tests.domain.goals.test_goal_commitment_store import decision, goal_transition
from tests.domain.memory import test_memory_store_retrieval as memory
from tests.infrastructure.postgresql.test_memory import POLICY
from tests.infrastructure.postgresql.test_runtime import runtime
from tests.runtime.test_lifecycle import retry_policy
from tests.system_integration.test_early_boot import no_provider


@pytest.fixture
def boot_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    no_provider(monkeypatch)
    source = yaml.safe_load(Path("resources/config/v2/minimum_brain.yaml").read_text())
    source["config_revision"] = 2
    source["shutdown"]["policy_revision"] = 2
    source["shutdown"]["final_persistence_grace_seconds"] = 2.0
    source["shutdown"]["resource_close_grace_seconds"] = 5.0
    path = tmp_path / "persistent.yaml"
    path.write_text(yaml.safe_dump(source, allow_unicode=True))
    return path


@pytest.mark.asyncio
async def test_boot_shares_restored_goals_and_memory_then_closes(
    endpoint: PostgresEndpoint,
    boot_config: Path,
) -> None:
    baseline = asyncio.all_tasks()
    first_runtime = runtime(endpoint)
    first = await build_persistent_core(
        boot_config,
        persistence=first_runtime,
        retry_policy=retry_policy("db", retry_enabled=False),
        runtime_epoch="first",
        max_pending_memory=2,
    )
    assert isinstance(first.goals, CoreGoalPersistenceBinding)
    assert first.memory is not None
    await first.start()
    try:
        changed = first.goals.apply(
            decision(
                "create",
                0,
                goals=(goal_transition(GoalTransitionOperation.CREATE, 0),),
            )
        )
        assert (await changed.durability).status is DurabilityStatus.DURABLE
        operation = first.memory.submit_write(MemoryWriteRequest(memory.candidate()))
        assert (await operation.wait()).failure_code is None
    finally:
        await first.stop()
    assert first_runtime.availability is PersistenceAvailability.CLOSED
    assert first_runtime.pending_task_count == 0
    second_runtime = runtime(endpoint)
    second = await build_persistent_core(
        boot_config,
        persistence=second_runtime,
        retry_policy=retry_policy("db", retry_enabled=False),
        runtime_epoch="second",
        max_pending_memory=2,
    )
    assert isinstance(second.goals, CoreGoalPersistenceBinding)
    assert second.memory is not None
    try:
        assert second.goals.snapshot() == changed.committed.snapshot
        context = second.input_context.snapshot()
        assert context.goals.goal_revision == 1
        assert len(context.context.entries) == 1
        changed_again = second.goals.apply(
            decision(
                "change",
                1,
                goals=(goal_transition(GoalTransitionOperation.REPRIORITIZE, 1),),
            )
        )
        assert second.input_context.snapshot().goals.goal_revision == 2
        assert (
            second.input_context.snapshot().context.source_context_revision
            > context.context.source_context_revision
        )
        assert (await changed_again.durability).status is DurabilityStatus.DURABLE
        result = await second.memory.submit_retrieval(memory.query()).wait()
        assert result.value is not None and len(result.value.items) == 1
    finally:
        await second.stop()
        await second.stop()
    assert second_runtime.pending_task_count == 0
    assert not (asyncio.all_tasks() - baseline)


@pytest.mark.asyncio
async def test_boot_restore_failure_keeps_saved_goal_after_reconnect(
    endpoint: PostgresEndpoint,
    boot_config: Path,
) -> None:
    seed = runtime(endpoint)
    await seed.start()
    binding = await CoreGoalPersistenceBinding.restore(seed, runtime_epoch="seed")
    saved = binding.apply(
        decision("seed", 0, goals=(goal_transition(GoalTransitionOperation.CREATE, 0),))
    )
    assert (await saved.durability).status is DurabilityStatus.DURABLE
    await seed.close()
    storage = runtime(endpoint)
    blocker = PostgresDatabase.connect(endpoint, POLICY)
    try:
        # 起動時の移行を先に済ませ、復元だけを実DBのロックで失敗させる。
        await storage.start()
        with blocker.transaction() as connection:
            connection.execute("LOCK TABLE yura_v2.lifecycle_snapshots IN ACCESS EXCLUSIVE MODE")
            app = await build_persistent_core(
                boot_config,
                persistence=storage,
                retry_policy=retry_policy("db", retry_enabled=False),
                runtime_epoch="failed",
                max_pending_memory=2,
            )
        try:
            assert isinstance(app.goals, CoreGoalPersistenceBinding)
            assert app.goals.restore_failure is PersistenceFailureCode.TIMEOUT
            assert app.input_context.snapshot().goals.goal_revision == 0
            await app.start()
            await storage.start()
            change = app.goals.apply(
                decision(
                    "temporary", 0, goals=(goal_transition(GoalTransitionOperation.CREATE, 0),)
                )
            )
            assert (await change.durability).failure_code is PersistenceFailureCode.TIMEOUT
            assert app.input_context.snapshot().goals.goal_revision == 1
        finally:
            await app.stop()
    finally:
        blocker.close()
        await storage.close()
    restarted = runtime(endpoint)
    await restarted.start()
    try:
        assert (await restarted.restore_goals()).value == saved.committed.snapshot
    finally:
        await restarted.close()


@pytest.mark.asyncio
async def test_invalid_configuration_closes_transferred_runtime(
    endpoint: PostgresEndpoint,
    boot_config: Path,
) -> None:
    storage = runtime(endpoint)
    with pytest.raises(ValueError, match="猶予"):
        await build_persistent_core(
            Path("resources/config/v2/minimum_brain.yaml"),
            persistence=storage,
            retry_policy=retry_policy("db"),
            runtime_epoch="invalid",
            max_pending_memory=2,
        )
    assert storage.availability is PersistenceAvailability.CLOSED
    assert storage.pending_task_count == 0


@pytest.mark.asyncio
async def test_cancelled_boot_reaps_runtime(
    endpoint: PostgresEndpoint,
    boot_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = asyncio.all_tasks()
    storage = runtime(endpoint)
    entered = asyncio.Event()
    original = PostgresPersistenceRuntime.restore_goals

    async def waiting(
        self: PostgresPersistenceRuntime,
    ) -> PersistenceOperationResult[GoalCommitmentSnapshot]:
        entered.set()
        await asyncio.Event().wait()
        return await original(self)

    monkeypatch.setattr(PostgresPersistenceRuntime, "restore_goals", waiting)
    task = asyncio.create_task(
        build_persistent_core(
            boot_config,
            persistence=storage,
            retry_policy=retry_policy("db"),
            runtime_epoch="cancelled",
            max_pending_memory=2,
        )
    )
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert storage.availability is PersistenceAvailability.CLOSED
    assert storage.pending_task_count == 0
    assert not (asyncio.all_tasks() - baseline)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_stop_reaps_memory_before_database_close(
    endpoint: PostgresEndpoint,
    boot_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    timeout: bool,
) -> None:
    from app.composition.memory_persistence import CoreMemoryPersistenceBinding
    from app.runtime.shutdown import RuntimeShutdownError, RuntimeShutdownStage

    baseline = asyncio.all_tasks()
    if timeout:
        data = yaml.safe_load(boot_config.read_text())
        data["shutdown"]["final_persistence_grace_seconds"] = 0.01
        boot_config.write_text(yaml.safe_dump(data))
    storage = runtime(endpoint)
    app = await build_persistent_core(
        boot_config,
        persistence=storage,
        retry_policy=retry_policy("db", retry_enabled=False),
        runtime_epoch="stop",
        max_pending_memory=2,
    )
    assert app.memory is not None
    entered, release = asyncio.Event(), asyncio.Event()
    cancelled = asyncio.Event()
    original = CoreMemoryPersistenceBinding.close

    async def delayed(self: CoreMemoryPersistenceBinding) -> None:
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            await original(self)
            raise
        await original(self)

    monkeypatch.setattr(CoreMemoryPersistenceBinding, "close", delayed)
    task = asyncio.create_task(app.stop())
    await asyncio.wait_for(entered.wait(), 2)
    if timeout:
        await asyncio.wait_for(cancelled.wait(), 2)
    else:
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
    assert not task.done()
    assert storage.availability.value == PersistenceAvailability.AVAILABLE.value
    release.set()
    if timeout:
        with pytest.raises(RuntimeShutdownError) as caught:
            await task
        assert caught.value.failures[0].stage is RuntimeShutdownStage.FINAL_PERSISTENCE
    else:
        with pytest.raises(asyncio.CancelledError):
            await task
    assert storage.availability is PersistenceAvailability.CLOSED
    assert storage.pending_task_count == 0
    assert app.memory.pending_count == 0
    assert not (asyncio.all_tasks() - baseline)


@pytest.mark.asyncio
async def test_missing_database_keeps_core_running_with_typed_failure(
    endpoint: PostgresEndpoint,
    boot_config: Path,
) -> None:
    from dataclasses import replace

    from app.domain.brain_integration import BrainWorkStatus
    from app.domain.input_meaning import InputMeaningInterpretationResult
    from app.runtime.lifecycle import DependencyState
    from tests.system_integration.test_early_boot import work

    baseline = asyncio.all_tasks()
    storage = runtime(replace(endpoint, host="/tmp/yura-missing-boot-test-socket"))
    app = await build_persistent_core(
        boot_config,
        persistence=storage,
        retry_policy=retry_policy("db", retry_enabled=False),
        runtime_epoch="unavailable",
        max_pending_memory=2,
    )
    try:
        assert app.lifecycle.snapshot("db").state is DependencyState.UNAVAILABLE
        assert (
            app.lifecycle.snapshot("db").last_failure_code
            == PersistenceFailureCode.CONNECTION_FAILED.value
        )
        assert isinstance(app.goals, CoreGoalPersistenceBinding)
        assert app.goals.restore_failure is PersistenceFailureCode.UNAVAILABLE
        await app.start()
        assert app.brain.submit(work()).accepted
        outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
        assert outcome.status is BrainWorkStatus.COMPLETED
        assert isinstance(outcome.result, InputMeaningInterpretationResult)
        assert app.memory is not None
        result = await app.memory.submit_retrieval(memory.query()).wait()
        assert result.failure_code is PersistenceFailureCode.UNAVAILABLE
    finally:
        await app.stop()
    assert storage.availability is PersistenceAvailability.CLOSED
    assert not (asyncio.all_tasks() - baseline)
