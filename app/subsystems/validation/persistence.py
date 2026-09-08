"""隔離DBと本番起動入口を共通Harnessへ接続する。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Mapping
from dataclasses import asdict, dataclass, replace
from enum import Enum
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from threading import Event
from typing import Any, TypeVar
from uuid import uuid4

from app.bootstrap import MinimumCoreApplication, build_persistent_core
from app.composition.goal_persistence import CoreGoalPersistenceBinding, GoalPersistenceCommitResult
from app.config.minimum_brain import load_minimum_brain_config
from app.domain.contracts.common import JsonValue, freeze_json, thaw_json
from app.domain.executive import CommittedExecutiveDecision
from app.domain.memory import MemoryRetrievalQuery, MemoryWriteRequest, MemoryWriteResult
from app.domain.memory.contracts import MemoryDisposition
from app.domain.memory.ranking import MemoryRetrievalRankingPolicy
from app.infrastructure.persistence import (
    DurabilityReceipt,
    DurabilityStatus,
    PersistenceAvailability,
    PersistenceOperationResult,
    PostgresPersistenceRuntime,
    SnapshotPersistenceRetryPolicy,
)
from app.infrastructure.persistence.postgresql_connection import (
    PostgresConnectionPolicy,
    PostgresDatabase,
    PostgresEndpoint,
)
from app.runtime.lifecycle import DependencyRetryPolicy, DependencyState
from app.runtime.shutdown import RuntimeShutdownError

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .memory import _project
from .provenance import capture_production_provenance
from .runtime import LabTarget, RunContext

T = TypeVar("T")


async def _settle(operation: Awaitable[T]) -> T:
    """取消されても、開始済みの資源操作の終了を先に回収する。"""
    task = asyncio.ensure_future(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


class PersistenceScenario(str, Enum):
    RESTART = "restart"
    DATABASE_UNAVAILABLE = "database_unavailable"
    RECONNECT = "reconnect"
    RESTORE_FAILURE = "restore_failure"
    FINAL_SAVE_TIMEOUT = "final_save_timeout"
    STOP_CANCELLED = "stop_cancelled"


@dataclass(frozen=True)
class PersistenceLabSettings:
    repository: Path
    config_path: Path
    admin_endpoint: PostgresEndpoint
    connection_policy: PostgresConnectionPolicy
    ranking_policy: MemoryRetrievalRankingPolicy
    snapshot_retry_policy: SnapshotPersistenceRetryPolicy
    retry_policy: DependencyRetryPolicy
    max_pending: int
    max_pending_memory: int

    def __post_init__(self) -> None:
        for value in (self.max_pending, self.max_pending_memory):
            if type(value) is not int or value <= 0:
                raise ValueError("永続化の受付上限は正の整数で指定してください")

    def runtime(self, endpoint: PostgresEndpoint) -> PostgresPersistenceRuntime:
        return PostgresPersistenceRuntime(
            endpoint,
            self.connection_policy,
            self.ranking_policy,
            max_pending=self.max_pending,
            snapshot_retry_policy=self.snapshot_retry_policy,
        )

    def public_settings(self) -> JsonValue:
        config_bytes = self.config_path.read_bytes()
        config = load_minimum_brain_config(config_bytes)
        return freeze_json(
            {
                "boot_config": {
                    "config_id": config.config_id,
                    "config_revision": config.config_revision,
                    "config_sha256": sha256(config_bytes).hexdigest(),
                    "shutdown_policy": asdict(config.shutdown_policy),
                },
                "connection_policy": asdict(self.connection_policy),
                "ranking_policy": _project(self.ranking_policy),
                "snapshot_retry_policy": asdict(self.snapshot_retry_policy),
                "retry_policy": asdict(self.retry_policy),
                "max_pending": self.max_pending,
                "max_pending_memory": self.max_pending_memory,
            }
        )


@dataclass(frozen=True)
class PersistenceLabCase:
    fixture: ValidationFixture
    scenario: PersistenceScenario
    goal_decision: CommittedExecutiveDecision
    memory_write: MemoryWriteRequest
    query: MemoryRetrievalQuery

    def typed_inputs(self, settings: PersistenceLabSettings) -> JsonValue:
        return freeze_json(
            {
                "scenario": self.scenario.value,
                "goal_decision": self.goal_decision.to_dict(),
                "memory_write": _project(self.memory_write),
                "query": _project(self.query),
                "settings": settings.public_settings(),
            }
        )


class _Database:
    """自分で生成したDBだけへ障害を注入し、終了時に削除する。"""

    def __init__(self, settings: PersistenceLabSettings) -> None:
        self.settings = settings
        self.endpoint = replace(settings.admin_endpoint, database="yura_lab_" + uuid4().hex)
        self.created = False

    def _execute(self, sql: str) -> None:
        psycopg: Any = import_module("psycopg")
        endpoint = self.settings.admin_endpoint
        with psycopg.connect(
            host=endpoint.host,
            port=endpoint.port,
            dbname=endpoint.database,
            user=endpoint.user,
            password=endpoint.password,
            sslmode=endpoint.sslmode,
            passfile="/dev/null",
            connect_timeout=self.settings.connection_policy.connect_timeout_seconds,
            options=f"-c statement_timeout={self.settings.connection_policy.statement_timeout_ms}",
            autocommit=True,
        ) as connection:
            connection.execute(sql)

    async def create(self) -> None:
        def create() -> None:
            self._execute(f'CREATE DATABASE "{self.endpoint.database}"')
            self.created = True

        await _settle(asyncio.to_thread(create))

    async def allow_connections(self, allowed: bool) -> None:
        if not self.created:
            raise ValueError("生成済みの検証DBだけへ障害を注入できます")
        await _settle(
            asyncio.to_thread(
                self._execute,
                f'ALTER DATABASE "{self.endpoint.database}" '
                f"ALLOW_CONNECTIONS {str(allowed).lower()}",
            )
        )

    async def close(self) -> None:
        if self.created:

            def drop() -> None:
                self._execute(f'DROP DATABASE "{self.endpoint.database}" WITH (FORCE)')
                self.created = False

            await _settle(asyncio.to_thread(drop))


class _TableLock:
    """既知の検証対象テーブルだけを別接続でロックする。"""

    def __init__(
        self, endpoint: PostgresEndpoint, policy: PostgresConnectionPolicy, table: str
    ) -> None:
        if table not in {"lifecycle_snapshots", "memory_records"}:
            raise ValueError("未登録の障害注入対象です")
        self.endpoint, self.policy, self.table = endpoint, policy, table
        self.entered = asyncio.Event()
        self.release = Event()
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()

        def hold() -> None:
            database = PostgresDatabase.connect(self.endpoint, self.policy)
            try:
                with database.transaction() as connection:
                    connection.execute(f"LOCK TABLE yura_v2.{self.table} IN ACCESS EXCLUSIVE MODE")
                    loop.call_soon_threadsafe(self.entered.set)
                    self.release.wait()
            finally:
                database.close()

        self.task = asyncio.create_task(asyncio.to_thread(hold))
        waiter = asyncio.create_task(self.entered.wait())
        try:
            await asyncio.wait((self.task, waiter), return_when=asyncio.FIRST_COMPLETED)
            if self.task.done():
                self.task.result()
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    async def wait_for_product(self) -> None:
        def blocked() -> bool:
            database = PostgresDatabase.connect(self.endpoint, self.policy)
            try:
                with database.transaction() as connection:
                    row = connection.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                        "AND pid <> pg_backend_pid()"
                    ).fetchone()
                    return row is not None and isinstance(row[0], int) and row[0] > 0
            finally:
                database.close()

        while not await asyncio.to_thread(blocked):
            await asyncio.sleep(0.001)

    async def close(self) -> None:
        self.release.set()
        if self.task is not None:
            await _settle(self.task)


class _SettingsChanged(ValueError):
    """fixtureに固定した公開設定が現在の起動構成と一致しない。"""


def _check_settings(settings: PersistenceLabSettings, expected: JsonValue) -> None:
    try:
        current = settings.public_settings()
    except (OSError, ValueError):
        raise _SettingsChanged("記録した起動設定を確認できません") from None
    if current != expected:
        raise _SettingsChanged("記録した起動設定が実行中に変更されました")


async def _boot(
    settings: PersistenceLabSettings,
    endpoint: PostgresEndpoint,
    epoch: str,
    expected_settings: JsonValue,
) -> tuple[MinimumCoreApplication, PostgresPersistenceRuntime]:
    _check_settings(settings, expected_settings)
    storage = settings.runtime(endpoint)
    app = await build_persistent_core(
        settings.config_path,
        persistence=storage,
        retry_policy=settings.retry_policy,
        runtime_epoch=epoch,
        max_pending_memory=settings.max_pending_memory,
    )
    try:
        await app.start()
        _check_settings(settings, expected_settings)
    except BaseException:
        await _settle(app.stop())
        raise
    return app, storage


def _state(
    app: MinimumCoreApplication, storage: PostgresPersistenceRuntime
) -> dict[str, JsonValue]:
    if not isinstance(app.goals, CoreGoalPersistenceBinding) or app.memory is None:
        raise ValueError("本番の永続化所有者が接続されていません")
    failure = app.goals.restore_failure
    return {
        "goals": freeze_json(app.goals.snapshot().to_dict()),
        "restore_failure": None if failure is None else failure.value,
        "availability": storage.availability.value,
        "pending_persistence": storage.pending_task_count,
        "pending_memory": app.memory.pending_count,
        "input_goal_revision": app.input_context.snapshot().goals.goal_revision,
    }


async def _stop(app: MinimumCoreApplication, storage: PostgresPersistenceRuntime) -> JsonValue:
    failures: list[JsonValue] = []
    try:
        await app.stop()
    except RuntimeShutdownError as error:
        failures = [
            freeze_json({"stage": x.stage.value, "error_class": x.error_class})
            for x in error.failures
        ]
    return freeze_json({**_state(app, storage), "shutdown_failures": failures})


async def _close_application(
    app: MinimumCoreApplication, storage: PostgresPersistenceRuntime
) -> None:
    await _stop(app, storage)
    if storage.availability is not PersistenceAvailability.CLOSED or storage.pending_task_count:
        raise RuntimeError("本番永続化の資源回収が未完了です")
    if app.memory is not None and app.memory.pending_count:
        raise RuntimeError("本番記憶の子処理回収が未完了です")


async def _register_application(
    context: RunContext, name: str, app: MinimumCoreApplication, storage: PostgresPersistenceRuntime
) -> None:
    try:
        context.add_cleanup(name, lambda: _close_application(app, storage))
    except BaseException:
        await _settle(_close_application(app, storage))
        raise


def _current_provenance(
    settings: PersistenceLabSettings, expected: ProductionTargetProvenance
) -> bool:
    actual = capture_production_provenance(
        settings.repository,
        (
            "app/bootstrap.py",
            "app/composition/goal_persistence.py",
            "app/composition/memory_persistence.py",
            "app/infrastructure/persistence",
        ),
        expected.module_contract_ids,
        expected.role_schema_ids,
    )
    return actual.git_head == expected.git_head and actual.branch == expected.branch


def _reported_status(outputs: Mapping[str, JsonValue]) -> RunStatus:
    failed = False
    for name in ("seed", "after_reconnect"):
        value = outputs.get(name)
        if isinstance(value, Mapping) and value.get("operation_failed") is True:
            failed = True
    value = outputs.get("failed_boot")
    if isinstance(value, Mapping) and value.get("restore_failure") is not None:
        failed = True
    for name in ("seed_stop", "recovered_stop"):
        value = outputs.get(name)
        if isinstance(value, Mapping):
            if value.get("stop_cancelled") is True:
                return RunStatus.CANCELLED
            if value.get("shutdown_failures"):
                failed = True
    value = outputs.get("restart")
    if isinstance(value, Mapping) and value.get("product_failed") is True:
        failed = True
    return RunStatus.PRODUCT_FAILED if failed else RunStatus.COMPLETED


async def _write(
    context: RunContext, app: MinimumCoreApplication, case: PersistenceLabCase
) -> JsonValue:
    if not isinstance(app.goals, CoreGoalPersistenceBinding) or app.memory is None:
        raise ValueError("本番の永続化所有者が接続されていません")
    goals, memory_owner = app.goals, app.memory

    async def apply() -> GoalPersistenceCommitResult:
        return goals.apply(case.goal_decision)

    result = await context.invoke_product("persistence.goal.apply", apply)

    async def durable() -> DurabilityReceipt:
        return await result.durability

    async def write() -> PersistenceOperationResult[MemoryWriteResult]:
        return await memory_owner.submit_write(case.memory_write).wait()

    receipt = await context.invoke_product("persistence.goal.durable", durable)
    memory = await context.invoke_product("persistence.memory.write", write)
    return freeze_json(
        {
            "goal_snapshot": result.committed.snapshot.to_dict(),
            "durability": {
                "request_id": receipt.persistence_request_id,
                "status": receipt.status.value,
                "owner_id": receipt.owner_id,
                "snapshot_or_record_ref": receipt.snapshot_or_record_ref,
                "durable_at": None
                if receipt.durable_at is None
                else receipt.durable_at.isoformat(),
                "storage_revision": receipt.storage_revision,
                "owner_state_revision": receipt.owner_state_revision,
                "failure_code": None
                if receipt.failure_code is None
                else receipt.failure_code.value,
            },
            "operation_failed": receipt.status is not DurabilityStatus.DURABLE
            or memory.failure_code is not None
            or memory.value is None
            or memory.value.disposition is MemoryDisposition.REJECT,
            "memory_failure": None if memory.failure_code is None else memory.failure_code.value,
            "memory_result": None if memory.value is None else _project(memory.value),
        }
    )


async def _restore_process(
    context: RunContext,
    settings: PersistenceLabSettings,
    endpoint: PostgresEndpoint,
    query: MemoryRetrievalQuery,
    provenance: ProductionTargetProvenance,
    expected_settings: JsonValue,
) -> JsonValue:
    packet = {
        "settings": thaw_json(expected_settings),
        "endpoint": asdict(endpoint),
        "config_path": str(settings.config_path.resolve()),
        "query": thaw_json(_project(query)),
        "run_id": context.run_id,
        "iteration": context.iteration,
        "provenance": asdict(provenance),
    }
    # 接続先・認証情報は引数や証拠ファイルへ出さず、専用pipeへ渡す。
    process: asyncio.subprocess.Process | None = None

    async def open_process() -> None:
        nonlocal process
        _check_settings(settings, expected_settings)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.subsystems.validation.persistence_process",
            cwd=settings.repository,
            env={},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def close() -> None:
        if process is not None:
            if process.returncode is None:
                process.kill()
            await process.wait()

    try:
        await _settle(open_process())
        context.add_cleanup("persistence.child", close)
    except BaseException:
        await _settle(close())
        raise
    assert process is not None
    output, _ = await process.communicate(
        json.dumps(packet, ensure_ascii=False, allow_nan=False).encode()
    )
    if process.returncode != 0 or len(output) > context.policy.max_export_bytes:
        raise RuntimeError("復元プロセスの正常終了と有限な証拠を確認できません")
    result: Any = json.loads(output)
    if result["run_id"] != context.run_id or result["iteration"] != context.iteration:
        raise ValueError("別プロセスの証拠の来歴が一致しません")
    if result["git_head"] != provenance.git_head or result["pid"] == os.getpid():
        raise ValueError("復元プロセスの製品由来が一致しません")
    return freeze_json(result)


def persistence_target(
    cases: tuple[PersistenceLabCase, ...],
    settings: PersistenceLabSettings,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    expected_settings = freeze_json(settings.public_settings())
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("永続化シナリオが重複しています")

    async def execute(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        _check_settings(settings, expected_settings)
        case = registered.get(fixture.scenario_id)
        if (
            case is None
            or case.fixture != fixture
            or case.typed_inputs(settings) != fixture.typed_inputs
        ):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        if not _current_provenance(settings, provenance):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        if (
            case.scenario is PersistenceScenario.RECONNECT
            and not settings.retry_policy.retry_enabled
        ):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)

        async def boot(epoch: str) -> tuple[MinimumCoreApplication, PostgresPersistenceRuntime]:
            _check_settings(settings, expected_settings)
            return await context.invoke_product(
                "persistence.product_boot",
                lambda: _boot(settings, database.endpoint, epoch, expected_settings),
            )

        database = _Database(settings)
        context.add_cleanup("persistence.database", database.close)
        await context.stage("persistence.database.create", database.create)
        outputs: dict[str, JsonValue] = {"scenario": case.scenario.value, "parent_pid": os.getpid()}
        first, storage = await context.stage(
            "persistence.boot",
            lambda: boot(context.run_id + "-seed"),
        )
        await _register_application(context, "persistence.seed.close", first, storage)
        outputs["seed"] = await context.stage(
            "persistence.write", lambda: _write(context, first, case)
        )
        outputs["seed_stop"] = await context.invoke_product(
            "persistence.stop", lambda: _stop(first, storage)
        )
        if case.scenario is PersistenceScenario.RESTART:
            outputs["restart"] = await context.stage(
                "persistence.process.restore",
                lambda: _restore_process(
                    context, settings, database.endpoint, case.query, provenance, expected_settings
                ),
            )
        elif case.scenario in {
            PersistenceScenario.DATABASE_UNAVAILABLE,
            PersistenceScenario.RECONNECT,
        }:
            await database.allow_connections(False)
            second, recovered = await context.stage(
                "persistence.failed_boot",
                lambda: boot(context.run_id + "-failed"),
            )
            await _register_application(context, "persistence.recovered.close", second, recovered)
            outputs["failed_boot"] = freeze_json(_state(second, recovered))
            owner = second.goals
            await database.allow_connections(True)
            if case.scenario is PersistenceScenario.RECONNECT:

                async def wait_recovery() -> None:
                    while (
                        second.lifecycle.snapshot(settings.retry_policy.dependency_id).state
                        is not DependencyState.AVAILABLE
                    ):
                        await asyncio.sleep(0.01)

                await context.stage("persistence.reconnect", wait_recovery)
                outputs["same_goal_owner"] = second.goals is owner
                outputs["after_reconnect"] = await context.stage(
                    "persistence.guarded_write", lambda: _write(context, second, case)
                )
            outputs["recovered_stop"] = await context.invoke_product(
                "persistence.recovered.stop", lambda: _stop(second, recovered)
            )
            outputs["restart"] = await context.stage(
                "persistence.process.restore",
                lambda: _restore_process(
                    context, settings, database.endpoint, case.query, provenance, expected_settings
                ),
            )
        elif case.scenario is PersistenceScenario.RESTORE_FAILURE:
            lock = _TableLock(database.endpoint, settings.connection_policy, "lifecycle_snapshots")
            context.add_cleanup("persistence.restore_lock", lock.close)
            await context.stage("persistence.restore_lock.acquire", lock.start)
            second, recovered = await context.stage(
                "persistence.failed_restore",
                lambda: boot(context.run_id + "-failed"),
            )
            await _register_application(context, "persistence.recovered.close", second, recovered)
            outputs["failed_boot"] = freeze_json(_state(second, recovered))
            await lock.close()
            await context.invoke_product("persistence.reconnect", recovered.start)
            outputs["after_reconnect"] = await context.stage(
                "persistence.guarded_write", lambda: _write(context, second, case)
            )
            outputs["recovered_stop"] = await context.invoke_product(
                "persistence.recovered.stop", lambda: _stop(second, recovered)
            )
            outputs["restart"] = await context.stage(
                "persistence.process.restore",
                lambda: _restore_process(
                    context, settings, database.endpoint, case.query, provenance, expected_settings
                ),
            )
        elif case.scenario in {
            PersistenceScenario.FINAL_SAVE_TIMEOUT,
            PersistenceScenario.STOP_CANCELLED,
        }:
            second, recovered = await context.stage(
                "persistence.stop_boot",
                lambda: boot(context.run_id + "-stop"),
            )
            await _register_application(context, "persistence.recovered.close", second, recovered)
            lock = _TableLock(database.endpoint, settings.connection_policy, "memory_records")
            context.add_cleanup("persistence.memory_lock", lock.close)
            await context.stage("persistence.memory_lock.acquire", lock.start)
            if second.memory is None:
                raise ValueError("本番の記憶接続がありません")
            operation = second.memory.submit_write(case.memory_write)
            await context.stage("persistence.write.blocked", lock.wait_for_product)

            async def stop_under_load() -> JsonValue:
                stopping = asyncio.create_task(_stop(second, recovered))
                try:
                    if case.scenario is PersistenceScenario.STOP_CANCELLED:
                        await asyncio.sleep(0)
                        stopping.cancel()
                        await asyncio.sleep(0)
                        stopping.cancel()
                        await lock.close()
                    try:
                        return await asyncio.shield(stopping)
                    except asyncio.CancelledError:
                        if not stopping.done():
                            raise
                        return freeze_json({**_state(second, recovered), "stop_cancelled": True})
                finally:
                    await lock.close()
                    await asyncio.gather(stopping, return_exceptions=True)

            outputs["recovered_stop"] = await context.invoke_product(
                "persistence.stop_under_load", stop_under_load
            )
            try:
                result = await operation.wait()
                outputs["pending_write_failure"] = (
                    None if result.failure_code is None else result.failure_code.value
                )
            except asyncio.CancelledError:
                outputs["pending_write_cancelled"] = True
        else:
            raise ValueError("未登録のシナリオです")
        if not _current_provenance(settings, provenance):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        await database.close()
        _check_settings(settings, expected_settings)
        outputs["database_reclaimed"] = not database.created
        return TargetObservation(_reported_status(outputs), Gate.NOT_RUN, freeze_json(outputs))

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        try:
            return await execute(context, fixture)
        except _SettingsChanged:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)

    return LabTarget(
        "persistence", contract_revision, frozenset({LabMode.INTEGRATED}), (), provenance, run
    )
