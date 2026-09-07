"""製品の判断を委譲し、検証自身の実行と所有タスクを管理する。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic_ns
from typing import TypeVar

from .contracts import (
    DelayInjection,
    FailureInjection,
    Gate,
    InjectedFailure,
    LabMode,
    LabPolicy,
    LabRunSpec,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    ValidationRunResult,
    WorkInterval,
    identifier,
)
from .diagnostics import DiagnosticCollector

T = TypeVar("T")


class ProductInvocationError(Exception):
    """製品入口が例外終了したことだけを保持し、詳細理由は推測しない。"""

    def __init__(self, stage: str) -> None:
        identifier(stage)
        self.stage = stage
        super().__init__("製品入口の呼出しが完了しませんでした")


class RunContext:
    """対象接続が生成する子処理を実行単位に所有する。"""

    def __init__(
        self,
        policy: LabPolicy,
        injections: tuple[DelayInjection, ...] = (),
        run_id: str = "validation",
        failures: tuple[FailureInjection, ...] = (),
    ) -> None:
        self.policy = policy
        self.run_id = run_id
        self.iteration = 0
        self.diagnostics = DiagnosticCollector(policy.max_intervals)
        self._failures = {item.stage: item for item in failures}
        self._failure_counts: dict[str, int] = {}
        self.intervals: list[WorkInterval] = []
        self._tasks: set[asyncio.Task[object]] = set()
        self._cleanups: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        self._started = 0
        self._closed = False
        self._injections = {item.stage: item for item in injections}
        self._invocations: dict[str, int] = {}

    def take_failure(self, stage: str) -> InjectedFailure | None:
        injection = self._failures.get(stage)
        if injection is None:
            return None
        count = self._failure_counts.get(stage, 0) + 1
        self._failure_counts[stage] = count
        return injection.closed_failure_kind if count <= injection.activation_count else None

    async def invoke_product(self, name: str, operation: Callable[[], Awaitable[T]]) -> T:
        """製品入口の例外終了を、検証自身の組立て・書出し失敗から区別する。"""

        async def invoke() -> T:
            try:
                return await operation()
            except Exception:
                raise ProductInvocationError(name) from None

        return await self.stage(name, invoke)

    async def invoke_port(
        self,
        name: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        """既存の呼出し結果を変更せず、接続境界でだけ指定遅延を入れる。"""
        self._invocations[name] = self._invocations.get(name, 0) + 1
        injection = self._injections.get(name)
        activation = self._invocations[name]

        async def invoke() -> T:
            if injection is not None and activation <= injection.activation_count:
                await asyncio.sleep(injection.duration)
            return await operation()

        return await self.stage(name, invoke)

    async def stage(self, name: str, operation: Callable[[], Awaitable[T]]) -> T:
        identifier(name)
        if self._closed or self._started >= self.policy.max_intervals:
            raise ValueError("検証の観測区間数が上限に達しています")
        self._started += 1
        iteration = self.iteration
        started = monotonic_ns()
        status = RunStatus.COMPLETED
        try:
            return await operation()
        except asyncio.CancelledError:
            status = RunStatus.CANCELLED
            raise
        except ProductInvocationError:
            status = RunStatus.PRODUCT_FAILED
            raise
        except Exception:
            status = RunStatus.HARNESS_FAILED
            raise
        finally:
            self.intervals.append(WorkInterval(name, iteration, started, monotonic_ns(), status))

    def spawn(self, name: str, operation: Callable[[], Awaitable[object]]) -> asyncio.Task[object]:
        if self._closed or len(self._tasks) >= self.policy.max_tasks:
            raise ValueError("検証の子処理数が上限に達しています")
        task = asyncio.create_task(self.stage(name, operation), name=f"validation:{name}")
        self._tasks.add(task)
        return task

    async def settle(self) -> None:
        """完了済みを含め、所有する子処理の例外を回収する。"""
        tasks = tuple(self._tasks)
        if tasks:
            await asyncio.gather(*tasks)
        self._tasks.difference_update(tasks)

    def add_cleanup(self, name: str, close: Callable[[], Awaitable[None]]) -> None:
        """接続生成元が自身の資源の終了処理を登録する。共有資源は登録しない。"""
        identifier(name)
        if self._closed or len(self._cleanups) >= self.policy.max_tasks:
            raise ValueError("終了処理の登録は停止済みか上限に達しています")
        if not callable(close):
            raise ValueError("終了処理は呼出し可能でなければなりません")
        self._cleanups.append((name, close))

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        failed = False
        while self._cleanups:
            _, close = self._cleanups.pop()
            try:
                await asyncio.wait_for(close(), timeout=self.policy.timeout_seconds)
            except asyncio.CancelledError:
                failed = True
            except Exception:
                failed = True
        if failed:
            raise RuntimeError("検証が所有する資源の終了処理に失敗しました")


TargetWork = Callable[[RunContext, ValidationFixture], Awaitable[TargetObservation]]


@dataclass(frozen=True)
class LabTarget:
    """起動時に登録する製品接続。入力ファイルから関数名やコードを解決しない。"""

    module: str
    contract_revision: str
    modes: frozenset[LabMode]
    provider_policy_refs: tuple[str, ...]
    provenance: ProductionTargetProvenance
    run: TargetWork
    delay_stages: frozenset[str] = frozenset()
    failure_stages: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for name in ("delay_stages", "failure_stages"):
            stages = frozenset(getattr(self, name))
            for stage in stages:
                identifier(stage)
            object.__setattr__(self, name, stages)
        identifier(self.module)
        identifier(self.contract_revision)
        modes = frozenset(self.modes)
        if not modes or any(not isinstance(mode, LabMode) for mode in modes):
            raise ValueError("登録する検証範囲が不正です")
        object.__setattr__(self, "modes", modes)
        refs = tuple(self.provider_policy_refs)
        for value in refs:
            identifier(value)
        object.__setattr__(self, "provider_policy_refs", refs)


class ValidationRunner:
    def __init__(self, targets: tuple[LabTarget, ...], policy: LabPolicy) -> None:
        self._targets = {target.module: target for target in targets}
        if len(self._targets) != len(targets):
            raise ValueError("検証対象の登録は重複できません")
        self._policy = policy
        self._active: dict[str, asyncio.Task[ValidationRunResult]] = {}
        self._results: dict[str, ValidationRunResult] = {}
        self._closed = False

    @property
    def pending_count(self) -> int:
        return sum(not task.done() for task in self._active.values())

    def result(self, run_id: str) -> ValidationRunResult:
        return self._results[run_id]

    def take_result(self, run_id: str) -> ValidationRunResult:
        return self._results.pop(run_id)

    async def run(self, spec: LabRunSpec, fixture: ValidationFixture) -> ValidationRunResult:
        if self._closed or spec.run_id in self._active or spec.run_id in self._results:
            raise ValueError("検証実行は停止済みか識別子が重複しています")
        if len(self._results) + len(self._active) >= self._policy.max_retained_results:
            raise ValueError("検証記録の保持上限です。取得済みの記録を回収してください")
        if len(self._active) >= self._policy.max_tasks:
            raise ValueError("同時検証数が上限に達しています")
        if spec.repeat_count > self._policy.max_repeats:
            raise ValueError("繰返し回数が上限を超えています")
        target = self._targets.get(spec.target_module)
        if target is None:
            raise ValueError("検証対象が登録されていません")
        task = asyncio.create_task(self._execute(target, spec, fixture), name=f"lab:{spec.run_id}")
        self._active[spec.run_id] = task
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            settled = asyncio.gather(task, return_exceptions=True)
            while not settled.done():
                try:
                    await asyncio.shield(settled)
                except asyncio.CancelledError:
                    # 呼出し側の再取消でも、内部の終了処理と結果回収を完遂する。
                    continue
            if not task.cancelled() and task.exception() is None:
                self._results[spec.run_id] = task.result()
            raise
        else:
            self._results[spec.run_id] = result
            return result
        finally:
            self._active.pop(spec.run_id, None)

    async def cancel(self, run_id: str) -> None:
        task = self._active.get(run_id)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._active.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(
        self,
        target: LabTarget,
        spec: LabRunSpec,
        fixture: ValidationFixture,
    ) -> ValidationRunResult:
        context = RunContext(
            self._policy, spec.delay_injections, spec.run_id, spec.failure_injections
        )
        observations: list[TargetObservation] = []
        blockers: tuple[str, ...] = ()
        status = RunStatus.COMPLETED
        gate = Gate.NOT_RUN

        async def execute_all() -> None:
            nonlocal status, gate
            for iteration in range(spec.repeat_count):
                context.iteration = iteration
                observation = await context.stage("target", lambda: target.run(context, fixture))
                await context.settle()
                if not isinstance(observation, TargetObservation):
                    raise ValueError("対象接続が検証観測を返していません")
                observations.append(observation)
                if observation.status is not RunStatus.COMPLETED:
                    status = observation.status
                    gate = observation.machine_gate
                    return
            gates = [item.machine_gate for item in observations]
            gate = (
                Gate.FAIL
                if Gate.FAIL in gates
                else Gate.PASS
                if all(item is Gate.PASS for item in gates)
                else Gate.NOT_RUN
            )

        try:
            if (
                not {item.stage for item in spec.delay_injections} <= target.delay_stages
                or not {item.stage for item in spec.failure_injections} <= target.failure_stages
                or spec.target_contract_revision != target.contract_revision
                or spec.mode not in target.modes
                or spec.provider_policy_refs != target.provider_policy_refs
                or spec.scenario_id != fixture.scenario_id
                or spec.fixture_revision != fixture.fixture_revision
            ):
                status = RunStatus.BLOCKED_UPSTREAM
                blockers = ("対象・検証範囲・方針・入力のリビジョンが一致しません",)
            else:
                await asyncio.wait_for(execute_all(), timeout=self._policy.timeout_seconds)
        except asyncio.TimeoutError:
            status, gate = RunStatus.TIMED_OUT, Gate.NOT_RUN
        except asyncio.CancelledError:
            status, gate = RunStatus.CANCELLED, Gate.NOT_RUN
        except ProductInvocationError as error:
            status, gate = RunStatus.PRODUCT_FAILED, Gate.NOT_RUN
            blockers = (f"製品入口が例外終了しました: {error.stage}",)
        except Exception:
            status, gate = RunStatus.HARNESS_FAILED, Gate.NOT_RUN
            blockers = ("検証接続の実行に失敗しました",)
        finally:
            try:
                await context.close()
            except Exception:
                status, gate = RunStatus.HARNESS_FAILED, Gate.NOT_RUN
                blockers = (*blockers, "検証が所有する資源の終了処理に失敗しました")
        return ValidationRunResult(
            spec,
            target.provenance,
            fixture,
            status,
            tuple(observations),
            tuple(context.intervals),
            gate,
            blockers,
            datetime.now(timezone.utc),
            context.diagnostics.snapshot(),
            context.diagnostics.dropped_count,
        )
