"""共通Harnessで本番永続化と別プロセス復元の証拠を取得する。"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest
import pytest_asyncio
import yaml

from app.domain.executive import GoalTransitionOperation
from app.domain.memory import MemoryWriteRequest
from app.infrastructure.persistence import SnapshotPersistenceRetryPolicy
from app.infrastructure.persistence.postgresql_connection import PostgresDatabase, PostgresEndpoint
from app.subsystems.validation import persistence as lab
from app.subsystems.validation.contracts import LabMode, LabPolicy, RunStatus
from app.subsystems.validation.persistence import (
    PersistenceLabCase,
    PersistenceLabSettings,
    PersistenceScenario,
    persistence_target,
)
from app.subsystems.validation.provenance import capture_production_provenance
from app.subsystems.validation.runtime import LabTarget, ValidationRunner
from tests.domain.goals.test_goal_commitment_store import decision, goal_transition
from tests.domain.memory import test_memory_store_retrieval as memory
from tests.domain.memory.policy_fixtures import retrieval_policy
from tests.infrastructure.postgresql.test_memory import POLICY
from tests.infrastructure.postgresql.test_persistent_boot import boot_config as boot_config
from tests.runtime.test_lifecycle import retry_policy
from tests.subsystems.validation.test_runtime import FIXTURE, spec

LAB_POLICY = LabPolicy(2, 16, 100, 1_000_000, 15, 4)


@pytest_asyncio.fixture
async def allocated_databases(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[list[lab._Database]]:
    allocated: list[lab._Database] = []
    original = lab._Database.__init__

    def track(self: lab._Database, settings: PersistenceLabSettings) -> None:
        original(self, settings)
        allocated.append(self)

    monkeypatch.setattr(lab._Database, "__init__", track)
    yield allocated

    def verify(database: lab._Database) -> None:
        assert not database.created
        admin = PostgresDatabase.connect(database.settings.admin_endpoint, POLICY)
        try:
            with admin.transaction() as connection:
                row = connection.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s",
                    (database.endpoint.database,),
                ).fetchone()
                assert row is None
        finally:
            admin.close()

    for database in allocated:
        await asyncio.to_thread(verify, database)


def make_target(settings: PersistenceLabSettings, case: PersistenceLabCase) -> LabTarget:
    provenance = capture_production_provenance(
        Path.cwd(), ("app/bootstrap.py",), ("persistence_repository_contracts",), ()
    )
    return persistence_target((case,), settings, provenance, "1")


def make_case(
    endpoint: PostgresEndpoint, config: Path, scenario: PersistenceScenario
) -> tuple[PersistenceLabSettings, PersistenceLabCase]:
    settings = PersistenceLabSettings(
        Path.cwd(),
        config,
        replace(endpoint, database="postgres"),
        POLICY,
        retrieval_policy(),
        SnapshotPersistenceRetryPolicy(1, 0, 0),
        retry_policy(
            "db",
            retry_enabled=scenario is PersistenceScenario.RECONNECT,
            initial_backoff_seconds=0.1,
        ),
        2,
        2,
    )
    case = PersistenceLabCase(
        FIXTURE,
        scenario,
        decision("seed", 0, goals=(goal_transition(GoalTransitionOperation.CREATE, 0),)),
        MemoryWriteRequest(memory.candidate()),
        memory.query(),
    )
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs(settings)))
    return settings, case


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", list(PersistenceScenario))
async def test_persistence_scenarios_use_real_boot_and_record_cleanup(
    endpoint: PostgresEndpoint,
    boot_config: Path,
    scenario: PersistenceScenario,
    allocated_databases: list[lab._Database],
) -> None:
    baseline = asyncio.all_tasks()
    if scenario is PersistenceScenario.FINAL_SAVE_TIMEOUT:
        config = yaml.safe_load(boot_config.read_text())
        config["shutdown"]["final_persistence_grace_seconds"] = 0.01
        boot_config.write_text(yaml.safe_dump(config))
    settings, case = make_case(endpoint, boot_config, scenario)
    provenance = capture_production_provenance(
        Path.cwd(),
        ("app/bootstrap.py",),
        ("persistence_repository_contracts",),
        (),
    )
    target = persistence_target((case,), settings, provenance, "1")
    policy = LabPolicy(2, 16, 100, 1_000_000, 15, 4)
    runner = ValidationRunner((target,), policy)
    try:
        result = await runner.run(
            replace(spec(), target_module="persistence", mode=LabMode.INTEGRATED), case.fixture
        )
        exported = json.loads(result.export_json(policy.max_export_bytes))
        expected = {
            PersistenceScenario.RESTART: RunStatus.COMPLETED,
            PersistenceScenario.STOP_CANCELLED: RunStatus.CANCELLED,
        }.get(scenario, RunStatus.PRODUCT_FAILED)
        assert result.status is expected, exported
        assert result.stage_results
        output = exported["stage_results"][0]["typed_outputs"]
        assert output["database_reclaimed"] is True
        assert output["seed"]["durability"]["status"] == "durable"
        assert output["seed_stop"]["availability"] == "closed"
        if "restart" in output:
            restored = output["restart"]
            assert restored["pid"] != output["parent_pid"]
            assert restored["git_head"] == provenance.git_head
            assert restored["restored"]["goals"] == output["seed"]["goal_snapshot"]
            assert restored["restored"]["input_goal_revision"] == 1
            assert len(restored["memory_result"]["items"]) == 1
            assert restored["stopped"]["availability"] == "closed"
            assert restored["stopped"]["pending_persistence"] == 0
        if scenario in {
            PersistenceScenario.DATABASE_UNAVAILABLE,
            PersistenceScenario.RECONNECT,
            PersistenceScenario.RESTORE_FAILURE,
        }:
            assert output["failed_boot"]["restore_failure"] is not None
        if scenario in {PersistenceScenario.RECONNECT, PersistenceScenario.RESTORE_FAILURE}:
            assert output["after_reconnect"]["durability"]["failure_code"] is not None
            assert output["after_reconnect"]["memory_failure"] is None
        if scenario is PersistenceScenario.FINAL_SAVE_TIMEOUT:
            assert output["recovered_stop"]["shutdown_failures"][0]["stage"] == "final_persistence"
        if scenario is PersistenceScenario.STOP_CANCELLED:
            assert output["recovered_stop"]["stop_cancelled"] is True
    finally:
        await runner.close()
    assert runner.pending_count == 0
    assert not (asyncio.all_tasks() - baseline)


@pytest.mark.asyncio
async def test_repeated_restart_isolates_databases_and_exports_no_endpoint(
    endpoint: PostgresEndpoint, boot_config: Path, allocated_databases: list[lab._Database]
) -> None:
    settings, case = make_case(endpoint, boot_config, PersistenceScenario.RESTART)
    runner = ValidationRunner((make_target(settings, case),), LAB_POLICY)
    try:
        result = await runner.run(
            replace(spec(), target_module="persistence", mode=LabMode.INTEGRATED, repeat_count=2),
            case.fixture,
        )
        assert result.status is RunStatus.COMPLETED
        assert len(result.stage_results) == 2
        assert len({database.endpoint.database for database in allocated_databases}) == 2
        exported = result.export_json(LAB_POLICY.max_export_bytes)
        for private in (endpoint.password, endpoint.host, endpoint.user, str(boot_config)):
            assert private not in exported
    finally:
        await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["settings", "head"])
async def test_stale_inputs_block_before_database_allocation(
    endpoint: PostgresEndpoint,
    boot_config: Path,
    allocated_databases: list[lab._Database],
    mismatch: str,
) -> None:
    settings, case = make_case(endpoint, boot_config, PersistenceScenario.RESTART)
    target = make_target(settings, case)
    if mismatch == "settings":
        boot_config.write_text(boot_config.read_text() + "\n# 変更後の設定\n")
    else:
        target = persistence_target(
            (case,), settings, replace(target.provenance, git_head="f" * 40), "1"
        )
    runner = ValidationRunner((target,), LAB_POLICY)
    try:
        result = await runner.run(
            replace(spec(), target_module="persistence", mode=LabMode.INTEGRATED), case.fixture
        )
        assert result.status is RunStatus.BLOCKED_UPSTREAM
        assert not allocated_databases
    finally:
        await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("capacity", [1, 2])
async def test_cleanup_registration_failure_closes_allocated_resources(
    endpoint: PostgresEndpoint,
    boot_config: Path,
    allocated_databases: list[lab._Database],
    capacity: int,
) -> None:
    baseline = asyncio.all_tasks()
    settings, case = make_case(endpoint, boot_config, PersistenceScenario.RESTART)
    runner = ValidationRunner(
        (make_target(settings, case),), replace(LAB_POLICY, max_tasks=capacity)
    )
    try:
        result = await runner.run(
            replace(spec(), target_module="persistence", mode=LabMode.INTEGRATED), case.fixture
        )
        assert result.status is RunStatus.HARNESS_FAILED
    finally:
        await runner.close()
    assert not (asyncio.all_tasks() - baseline)


@pytest.mark.asyncio
async def test_repeated_cancellation_during_child_start_reaps_process_and_database(
    endpoint: PostgresEndpoint,
    boot_config: Path,
    allocated_databases: list[lab._Database],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = asyncio.all_tasks()
    entered, release = asyncio.Event(), asyncio.Event()
    processes: list[asyncio.subprocess.Process] = []
    original = asyncio.create_subprocess_exec

    async def start(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        process = await original(*args, **kwargs)  # type: ignore[arg-type]
        processes.append(process)
        entered.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    settings, case = make_case(endpoint, boot_config, PersistenceScenario.RESTART)
    runner = ValidationRunner((make_target(settings, case),), LAB_POLICY)
    running = asyncio.create_task(
        runner.run(
            replace(spec(), target_module="persistence", mode=LabMode.INTEGRATED), case.fixture
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        running.cancel()
        await asyncio.sleep(0)
        running.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await running
        result = runner.result("run")
        assert result is not None and result.status is RunStatus.CANCELLED
        assert processes and all(process.returncode is not None for process in processes)
    finally:
        release.set()
        await runner.close()
    assert not (asyncio.all_tasks() - baseline)
