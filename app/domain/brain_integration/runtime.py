"""#334 Brain IntegrationのRuntime Kernel結合実装。"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

from app.domain.contracts import RevisionVector
from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
    utc_instant,
)
from app.runtime.kernel import (
    CancellationToken,
    QueuePolicy,
    RuntimeClock,
    RuntimeCoordinator,
    RuntimeLanePolicy,
    RuntimeSchedulerPolicy,
    RuntimeWorkItem,
    WorkDisposition,
    WorkOutcome,
    WorkPriority,
)
from app.runtime.shutdown import RuntimeShutdownPolicy

from .contracts import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationTerminalOutcome,
    BrainIntegrationTrace,
    BrainRevisionEvent,
    BrainWorkEnvelope,
    BrainWorkInterval,
    BrainWorkPriority,
    BrainWorkStatus,
)


class BrainWorkAdmissionStatus(str, Enum):
    ACCEPTED = "accepted"
    PREREQUISITE_PENDING = "prerequisite_pending"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class BrainWorkAdmission:
    status: BrainWorkAdmissionStatus
    work_id: str
    blocked_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.work_id, "work_id")
        object.__setattr__(self, "blocked_by", _identifiers(self.blocked_by, "blocked_by"))

    @property
    def accepted(self) -> bool:
        return self.status is BrainWorkAdmissionStatus.ACCEPTED


@dataclass(frozen=True, slots=True)
class BrainIntegrationWork:
    work_id: str
    module: BrainIntegrationModule
    lane: BrainIntegrationLane
    envelope: BrainWorkEnvelope
    payload: object
    prerequisite_work_ids: tuple[str, ...] = ()
    queue_key: str | None = None
    deadline_at: datetime | None = None
    interruptible: bool = True

    def __post_init__(self) -> None:
        require_identifier(self.work_id, "work_id")
        if not isinstance(self.module, BrainIntegrationModule):
            raise ValueError("module が不正です")
        if not isinstance(self.lane, BrainIntegrationLane):
            raise ValueError("lane が不正です")
        object.__setattr__(
            self,
            "prerequisite_work_ids",
            _identifiers(self.prerequisite_work_ids, "prerequisite_work_ids"),
        )
        if self.work_id in self.prerequisite_work_ids:
            raise ValueError("work_id 自身を prerequisite にできません")
        if self.queue_key is not None:
            require_identifier(self.queue_key, "queue_key")
        if self.deadline_at is not None:
            require_aware(self.deadline_at, "deadline_at")
            if utc_instant(self.deadline_at) <= utc_instant(self.envelope.created_at):
                raise ValueError("deadline_at は created_at より後でなければなりません")
        if type(self.interruptible) is not bool:
            raise ValueError("interruptible は bool でなければなりません")


@dataclass(frozen=True, slots=True)
class BrainIntegrationWorkOutcome:
    work_id: str
    trace_id: str
    module: BrainIntegrationModule
    lane: BrainIntegrationLane
    status: BrainWorkStatus
    completed_at: datetime
    result: object | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.work_id, "work_id")
        require_identifier(self.trace_id, "trace_id")
        require_aware(self.completed_at, "completed_at")
        if self.status not in _TERMINAL_STATUSES:
            raise ValueError("outcome は終了状態でなければなりません")
        if self.error is not None:
            require_identifier(self.error, "error")


@dataclass(frozen=True, slots=True)
class BrainIntegrationRuntimePolicy:
    policy_id: str
    policy_revision: int
    scheduler_policy: RuntimeSchedulerPolicy
    lane_policies: tuple[RuntimeLanePolicy, ...]
    shutdown_policy: RuntimeShutdownPolicy | None = None

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        lanes = tuple(self.lane_policies)
        if len(lanes) != len(BrainIntegrationLane):
            raise ValueError("Brain lane policy は全laneをexactly once定義する必要があります")
        by_lane: dict[BrainIntegrationLane, RuntimeLanePolicy] = {}
        for lane_policy in lanes:
            try:
                lane = BrainIntegrationLane(lane_policy.lane_id)
            except ValueError as error:
                raise ValueError("未知のBrain lane policyがあります") from error
            if lane in by_lane:
                raise ValueError("Brain lane policy は重複できません")
            if lane_policy.queue_policy is QueuePolicy.COALESCE:
                raise ValueError(
                    "#334はowner payloadの意味的coalesceを推測できないためCOALESCEを使用できません"
                )
            by_lane[lane] = lane_policy
        if set(by_lane) != set(BrainIntegrationLane):
            raise ValueError("Brain lane policy coverage が不完全です")
        if not isinstance(self.shutdown_policy, RuntimeShutdownPolicy):
            raise ValueError("Runtime shutdown policy が必要です")
        object.__setattr__(self, "lane_policies", lanes)


class BrainModulePort(Protocol):
    def is_fresh(self, work: BrainIntegrationWork) -> bool: ...

    async def execute(
        self,
        work: BrainIntegrationWork,
        cancellation: CancellationToken,
    ) -> object: ...


@dataclass(slots=True)
class _TrackedWork:
    work: BrainIntegrationWork
    status: BrainWorkStatus
    queued_at: datetime | None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    terminal_override: BrainWorkStatus | None = None


@dataclass(slots=True)
class _TraceState:
    root_trigger_id: str
    source_event_ids: tuple[str, ...]
    work_ids: list[str] = field(default_factory=list)
    revision_events: list[BrainRevisionEvent] = field(default_factory=list)
    decision_ids: list[str] = field(default_factory=list)
    goal_transition_ids: list[str] = field(default_factory=list)
    activity_ids: list[str] = field(default_factory=list)
    speech_candidate_ids: list[str] = field(default_factory=list)
    terminal_outcome: BrainIntegrationTerminalOutcome | None = None


_TERMINAL_STATUSES = frozenset(
    {
        BrainWorkStatus.COMPLETED,
        BrainWorkStatus.CANCELLED,
        BrainWorkStatus.TIMED_OUT,
        BrainWorkStatus.STALE,
        BrainWorkStatus.SUPERSEDED,
        BrainWorkStatus.REJECTED,
        BrainWorkStatus.FAILED,
    }
)


def _identifiers(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{field_name} は配列でなければなりません")
    result = tuple(values)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError(f"{field_name} は空でない識別子の配列でなければなりません")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} は重複できません")
    return result


def _runtime_priority(priority: BrainWorkPriority) -> WorkPriority:
    if priority is BrainWorkPriority.BACKGROUND:
        return WorkPriority.BACKGROUND
    if priority is BrainWorkPriority.NORMAL:
        return WorkPriority.NORMAL
    return WorkPriority.FOREGROUND


class BrainIntegrationRuntime:
    """Owner semanticsを持たず、#334の結合責務だけを実行する。"""

    def __init__(
        self,
        clock: RuntimeClock,
        policy: BrainIntegrationRuntimePolicy,
    ) -> None:
        self._clock = clock
        self._policy = policy
        shutdown_policy = policy.shutdown_policy
        if shutdown_policy is None:
            raise ValueError("Runtime shutdown policy が必要です")
        self._runtime = RuntimeCoordinator(clock, policy.scheduler_policy, shutdown_policy)
        self._ports: dict[BrainIntegrationModule, BrainModulePort] = {}
        self._tracked: dict[str, _TrackedWork] = {}
        self._traces: dict[str, _TraceState] = {}
        self._synthetic_outcomes: asyncio.Queue[BrainIntegrationWorkOutcome] = asyncio.Queue()
        self._ready_outcomes: deque[BrainIntegrationWorkOutcome] = deque()
        self._started = False

        for lane_policy in policy.lane_policies:
            self._runtime.register_lane(
                lane_policy,
                self._execute_runtime_work,
                stale_validator=self._is_runtime_work_fresh,
            )

    @property
    def policy(self) -> BrainIntegrationRuntimePolicy:
        return self._policy

    def register_module(
        self,
        module: BrainIntegrationModule,
        port: BrainModulePort,
    ) -> None:
        if self._started:
            raise RuntimeError("Brain module registration は start 前だけ許可されます")
        if not isinstance(module, BrainIntegrationModule):
            raise ValueError("module が不正です")
        if module in self._ports:
            raise ValueError(f"Brain module は既に登録済みです: {module.value}")
        self._ports[module] = port

    async def start(self) -> None:
        if not self._ports:
            raise RuntimeError("Brain module が1件も登録されていません")
        await self._runtime.start()
        self._started = True

    async def stop(self) -> None:
        await self._runtime.stop()

    def submit(self, work: BrainIntegrationWork) -> BrainWorkAdmission:
        if work.work_id in self._tracked:
            return BrainWorkAdmission(BrainWorkAdmissionStatus.REJECTED, work.work_id)
        blocked_by = tuple(
            prerequisite
            for prerequisite in work.prerequisite_work_ids
            if not self._is_completed(prerequisite)
        )
        if blocked_by:
            return BrainWorkAdmission(
                BrainWorkAdmissionStatus.PREREQUISITE_PENDING,
                work.work_id,
                blocked_by,
            )

        now = self._clock.now()
        self._ensure_trace(work)
        tracked = _TrackedWork(work, BrainWorkStatus.QUEUED, now)
        self._tracked[work.work_id] = tracked

        if work.module not in self._ports:
            self._complete_synthetic(
                tracked,
                BrainWorkStatus.REJECTED,
                now,
                error="UNREGISTERED_MODULE",
            )
            return BrainWorkAdmission(BrainWorkAdmissionStatus.REJECTED, work.work_id)

        admission = self._runtime.submit(
            RuntimeWorkItem(
                work.work_id,
                work.lane.value,
                work,
                _runtime_priority(work.envelope.priority),
                RevisionVector(
                    work.envelope.source_context_revision,
                    work.envelope.goal_revision,
                    work.envelope.attention_revision,
                ),
                work.envelope.created_at,
                work.queue_key,
                work.deadline_at,
                work.interruptible,
            )
        )
        if not admission.accepted:
            self._complete_synthetic(
                tracked,
                BrainWorkStatus.REJECTED,
                self._clock.now(),
                error="RUNTIME_ADMISSION_REJECTED",
            )
            return BrainWorkAdmission(BrainWorkAdmissionStatus.REJECTED, work.work_id)

        for displaced_work_id in admission.displaced_work_ids:
            displaced = self._tracked.get(displaced_work_id)
            if displaced is not None and displaced.status not in _TERMINAL_STATUSES:
                self._complete_synthetic(
                    displaced,
                    BrainWorkStatus.SUPERSEDED,
                    self._clock.now(),
                    error="QUEUE_DISPLACED",
                )
        return BrainWorkAdmission(BrainWorkAdmissionStatus.ACCEPTED, work.work_id)

    def cancel(self, work_id: str, reason: str) -> bool:
        require_identifier(work_id, "work_id")
        require_identifier(reason, "reason")
        return self._runtime.cancel(work_id, reason)

    def supersede(self, work_id: str, reason: str) -> bool:
        require_identifier(work_id, "work_id")
        require_identifier(reason, "reason")
        tracked = self._tracked.get(work_id)
        if tracked is None or tracked.status in _TERMINAL_STATUSES:
            return False
        cancelled = self._runtime.cancel(work_id, reason)
        if cancelled:
            tracked.terminal_override = BrainWorkStatus.SUPERSEDED
        return cancelled

    async def next_outcome(self) -> BrainIntegrationWorkOutcome:
        if self._ready_outcomes:
            return self._ready_outcomes.popleft()
        try:
            return self._synthetic_outcomes.get_nowait()
        except asyncio.QueueEmpty:
            pass

        synthetic_task = asyncio.create_task(self._synthetic_outcomes.get())
        runtime_task = asyncio.create_task(self._runtime.next_outcome())
        tasks = (synthetic_task, runtime_task)
        try:
            done, _ = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            # この呼出しが生成した待機は、取消・例外時も必ず回収する。
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if synthetic_task in done and runtime_task in done:
            self._ready_outcomes.append(self._map_runtime_outcome(runtime_task.result()))
            return synthetic_task.result()
        if synthetic_task in done:
            return synthetic_task.result()
        return self._map_runtime_outcome(runtime_task.result())

    def record_revision_event(self, trace_id: str, event: BrainRevisionEvent) -> None:
        state = self._trace_state(trace_id)
        if any(item.revision_event_id == event.revision_event_id for item in state.revision_events):
            raise ValueError("revision event id は重複できません")
        state.revision_events.append(event)

    def record_decision_id(self, trace_id: str, decision_id: str) -> None:
        self._append_identity(self._trace_state(trace_id).decision_ids, decision_id, "decision_id")

    def record_goal_transition_id(self, trace_id: str, transition_id: str) -> None:
        self._append_identity(
            self._trace_state(trace_id).goal_transition_ids,
            transition_id,
            "goal_transition_id",
        )

    def record_activity_id(self, trace_id: str, activity_id: str) -> None:
        self._append_identity(self._trace_state(trace_id).activity_ids, activity_id, "activity_id")

    def record_speech_candidate_id(self, trace_id: str, candidate_id: str) -> None:
        self._append_identity(
            self._trace_state(trace_id).speech_candidate_ids,
            candidate_id,
            "speech_candidate_id",
        )

    def trace(self, trace_id: str) -> BrainIntegrationTrace:
        state = self._trace_state(trace_id)
        intervals = tuple(self._interval(self._tracked[work_id]) for work_id in state.work_ids)
        return BrainIntegrationTrace(
            trace_id,
            state.root_trigger_id,
            state.source_event_ids,
            intervals,
            tuple(state.revision_events),
            tuple(state.decision_ids),
            tuple(state.goal_transition_ids),
            tuple(state.activity_ids),
            tuple(state.speech_candidate_ids),
            state.terminal_outcome,
        )

    def finalize_trace(
        self,
        trace_id: str,
        outcome: BrainIntegrationTerminalOutcome,
    ) -> BrainIntegrationTrace:
        state = self._trace_state(trace_id)
        if state.terminal_outcome is not None:
            raise ValueError("trace は既に終了しています")
        if any(
            self._tracked[work_id].status not in _TERMINAL_STATUSES
            for work_id in state.work_ids
        ):
            raise ValueError("未終了workがあるtraceは終了できません")
        state.terminal_outcome = outcome
        return self.trace(trace_id)

    async def _execute_runtime_work(
        self,
        runtime_work: RuntimeWorkItem[object],
        cancellation: CancellationToken,
    ) -> object:
        work = self._brain_work(runtime_work)
        tracked = self._tracked[work.work_id]
        tracked.status = BrainWorkStatus.RUNNING
        tracked.started_at = self._clock.now()
        return await self._ports[work.module].execute(work, cancellation)

    def _is_runtime_work_fresh(self, runtime_work: RuntimeWorkItem[object]) -> bool:
        work = self._brain_work(runtime_work)
        port = self._ports.get(work.module)
        return port is not None and port.is_fresh(work)

    def _map_runtime_outcome(
        self,
        runtime_outcome: WorkOutcome[object],
    ) -> BrainIntegrationWorkOutcome:
        work_id = runtime_outcome.work_id
        disposition = runtime_outcome.disposition
        completed_at = runtime_outcome.completed_at
        result = runtime_outcome.result
        error = runtime_outcome.error
        tracked = self._tracked[work_id]
        status = tracked.terminal_override or _status_from_disposition(disposition)
        tracked.status = status
        tracked.completed_at = completed_at
        tracked.terminal_override = None
        return BrainIntegrationWorkOutcome(
            work_id,
            tracked.work.envelope.trace_id,
            tracked.work.module,
            tracked.work.lane,
            status,
            completed_at,
            result,
            error,
        )

    def _complete_synthetic(
        self,
        tracked: _TrackedWork,
        status: BrainWorkStatus,
        completed_at: datetime,
        *,
        error: str | None,
    ) -> None:
        tracked.status = status
        tracked.completed_at = completed_at
        self._synthetic_outcomes.put_nowait(
            BrainIntegrationWorkOutcome(
                tracked.work.work_id,
                tracked.work.envelope.trace_id,
                tracked.work.module,
                tracked.work.lane,
                status,
                completed_at,
                error=error,
            )
        )

    def _ensure_trace(self, work: BrainIntegrationWork) -> None:
        trace_id = work.envelope.trace_id
        state = self._traces.get(trace_id)
        if state is None:
            state = _TraceState(
                work.envelope.trigger_id,
                work.envelope.source_event_ids,
            )
            self._traces[trace_id] = state
        else:
            if state.root_trigger_id != work.envelope.trigger_id:
                raise ValueError("同一trace_idでroot triggerを変更できません")
            if state.terminal_outcome is not None:
                raise ValueError("終了済みtraceへworkを追加できません")
        state.work_ids.append(work.work_id)

    def _is_completed(self, work_id: str) -> bool:
        tracked = self._tracked.get(work_id)
        return tracked is not None and tracked.status is BrainWorkStatus.COMPLETED

    def _trace_state(self, trace_id: str) -> _TraceState:
        require_identifier(trace_id, "trace_id")
        try:
            return self._traces[trace_id]
        except KeyError as error:
            raise KeyError(f"未知のtrace_idです: {trace_id}") from error

    @staticmethod
    def _brain_work(runtime_work: RuntimeWorkItem[object]) -> BrainIntegrationWork:
        if not isinstance(runtime_work.payload, BrainIntegrationWork):
            raise TypeError("#334 Runtime laneはBrainIntegrationWorkだけを受理します")
        return runtime_work.payload

    @staticmethod
    def _interval(tracked: _TrackedWork) -> BrainWorkInterval:
        return BrainWorkInterval(
            tracked.work.work_id,
            tracked.work.module,
            tracked.work.lane,
            tracked.status,
            tracked.queued_at,
            tracked.started_at,
            tracked.completed_at,
            tracked.work.envelope.source_context_revision,
            tracked.work.envelope.goal_revision,
            tracked.work.envelope.attention_revision,
        )

    @staticmethod
    def _append_identity(values: list[str], value: str, field_name: str) -> None:
        require_identifier(value, field_name)
        if value in values:
            raise ValueError(f"{field_name} は重複できません")
        values.append(value)


def _status_from_disposition(disposition: WorkDisposition) -> BrainWorkStatus:
    mapping = {
        WorkDisposition.COMPLETED: BrainWorkStatus.COMPLETED,
        WorkDisposition.FAILED: BrainWorkStatus.FAILED,
        WorkDisposition.CANCELLED: BrainWorkStatus.CANCELLED,
        WorkDisposition.TIMED_OUT: BrainWorkStatus.TIMED_OUT,
        WorkDisposition.STALE: BrainWorkStatus.STALE,
        WorkDisposition.SUPERSEDED: BrainWorkStatus.SUPERSEDED,
        WorkDisposition.REJECTED: BrainWorkStatus.REJECTED,
    }
    return mapping[disposition]
