"""#341の非停止Body Integration orchestration。Authorityは各ownerへ委譲する。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from math import isfinite
from typing import Protocol

from app.domain.body import CanonicalBodyModel
from app.domain.body_motion_planning import BodyMotionPlan, BodyMotionPlanningContextSnapshot
from app.domain.body_realtime import BodyRealtimeRuntime, RealtimeOverlayBundle
from app.domain.body_solver import (
    BodyContinuousController,
    BodyControllerTickResult,
    BodyMotionExecutionStatus,
    BodySolverPolicy,
    BodyStateAuthority,
    LatestBodyFrameBuffer,
    compile_body_motion_plan,
)
from app.domain.contracts.common import require_aware, require_identifier

from .contracts import BodyExecutionSession, BodyExecutionSessionStatus, BodyIntegrationTrace


class BodyMotionPlanningPort(Protocol):
    async def plan(
        self,
        snapshot: BodyMotionPlanningContextSnapshot,
        *,
        candidate_id: str,
        plan_id: str,
        created_at: datetime,
    ) -> BodyMotionPlan: ...


@dataclass(frozen=True, slots=True)
class BodyPlanningSubmission:
    session_id: str
    command_id: str
    snapshot: BodyMotionPlanningContextSnapshot
    candidate_id: str
    plan_id: str
    trajectory_id: str
    trajectory_duration_s: float
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "session_id",
            "command_id",
            "candidate_id",
            "plan_id",
            "trajectory_id",
        ):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.snapshot, BodyMotionPlanningContextSnapshot):
            raise ValueError("snapshotが不正です")
        if (
            type(self.trajectory_duration_s) not in (int, float)
            or not isfinite(self.trajectory_duration_s)
            or self.trajectory_duration_s <= 0
        ):
            raise ValueError("trajectory_duration_sは正の有限値でなければなりません")
        object.__setattr__(self, "trajectory_duration_s", float(self.trajectory_duration_s))
        require_aware(self.created_at, "created_at")


class BodyIntegrationRuntime:
    """slow plannerとrealtime/physical tickをserial awaitへ結合しない。"""

    def __init__(
        self,
        model: CanonicalBodyModel,
        solver_policy: BodySolverPolicy,
        authority: BodyStateAuthority,
        controller: BodyContinuousController,
        planner: BodyMotionPlanningPort,
        frame_buffer: LatestBodyFrameBuffer,
    ) -> None:
        if not isinstance(model, CanonicalBodyModel):
            raise ValueError("modelが不正です")
        if not isinstance(solver_policy, BodySolverPolicy):
            raise ValueError("solver_policyが不正です")
        if not isinstance(authority, BodyStateAuthority):
            raise ValueError("authorityが不正です")
        if not isinstance(controller, BodyContinuousController):
            raise ValueError("controllerが不正です")
        if not hasattr(planner, "plan"):
            raise ValueError("plannerが不正です")
        if not isinstance(frame_buffer, LatestBodyFrameBuffer):
            raise ValueError("frame_bufferが不正です")
        current = authority.current
        if current.body_model_id != model.body_model_id:
            raise ValueError("BodyStateとmodelが一致しません")
        self._model = model
        self._solver_policy = solver_policy
        self._authority = authority
        self._controller = controller
        self._planner = planner
        self._frame_buffer = frame_buffer
        self._latest_overlay: RealtimeOverlayBundle | None = None
        self._planning_task: asyncio.Task[BodyMotionPlan] | None = None
        self._planning_submission: BodyPlanningSubmission | None = None
        self._planning_generation = 0
        self._retired_tasks: list[tuple[int, asyncio.Task[BodyMotionPlan]]] = []
        self._sessions: dict[str, BodyExecutionSession] = {}
        self._active_session_id: str | None = None
        self._realtime_runtime: BodyRealtimeRuntime | None = None
        self._started = False
        self._closed = False

    @property
    def pending_task_count(self) -> int:
        planning = int(self._planning_task is not None and not self._planning_task.done())
        retired = sum(not task.done() for _, task in self._retired_tasks)
        realtime = 0 if self._realtime_runtime is None else self._realtime_runtime.pending_task_count
        return planning + retired + realtime

    @property
    def controller(self) -> BodyContinuousController:
        return self._controller

    def session(self, session_id: str) -> BodyExecutionSession | None:
        require_identifier(session_id, "session_id")
        return self._sessions.get(session_id)

    @property
    def active_session(self) -> BodyExecutionSession | None:
        if self._active_session_id is None:
            return None
        return self._sessions.get(self._active_session_id)

    def attach_realtime_runtime(self, runtime: BodyRealtimeRuntime) -> None:
        if self._started or self._closed or self._realtime_runtime is not None:
            raise RuntimeError("realtime runtimeはstart前に一度だけattachできます")
        if not isinstance(runtime, BodyRealtimeRuntime):
            raise ValueError("runtimeが不正です")
        self._realtime_runtime = runtime

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("closed integration runtimeは再開できません")
        if self._started:
            return
        self._started = True
        if self._realtime_runtime is not None:
            self._realtime_runtime.start()

    def publish_overlay(self, bundle: RealtimeOverlayBundle) -> None:
        if not isinstance(bundle, RealtimeOverlayBundle):
            raise ValueError("bundleが不正です")
        self._latest_overlay = bundle

    def submit_planning(
        self,
        submission: BodyPlanningSubmission,
        *,
        supersede_allowed: bool,
    ) -> BodyExecutionSession:
        if self._closed:
            raise RuntimeError("closed integration runtimeへsubmitできません")
        if not isinstance(submission, BodyPlanningSubmission):
            raise ValueError("submissionが不正です")
        if type(supersede_allowed) is not bool:
            raise ValueError("supersede_allowedはboolでなければなりません")
        if submission.session_id in self._sessions:
            raise ValueError("session_idは一意でなければなりません")
        if submission.snapshot.body_model.body_model_id != self._model.body_model_id:
            raise ValueError("planning snapshotのbody modelが不一致です")

        current_task = self._planning_task
        current_submission = self._planning_submission
        if current_task is not None and not current_task.done():
            if not supersede_allowed:
                raise RuntimeError("pending planningをsupersedeできません")
            current_task.cancel()
            self._retired_tasks.append((self._planning_generation, current_task))
            if current_submission is not None:
                self._terminalize_planning_session(
                    current_submission.session_id,
                    BodyExecutionSessionStatus.SUPERSEDED,
                    submission.created_at,
                    "planning_superseded",
                )

        self._planning_generation += 1
        self._planning_submission = submission
        trace = self._trace_for(submission)
        session = BodyExecutionSession(
            submission.session_id,
            trace,
            BodyExecutionSessionStatus.PLANNING,
            None,
            self._authority.current.revision,
        )
        self._sessions[session.session_id] = session
        self._planning_task = asyncio.create_task(
            self._planner.plan(
                submission.snapshot,
                candidate_id=submission.candidate_id,
                plan_id=submission.plan_id,
                created_at=submission.created_at,
            ),
            name=f"body-planning:{submission.session_id}",
        )
        return session

    def tick_physical(
        self,
        *,
        observed_at: datetime,
        monotonic_now_s: float,
        active_support_contact_ids: tuple[str, ...],
        frame_id: str,
        trace_id: str,
    ) -> BodyControllerTickResult:
        if self._closed:
            raise RuntimeError("closed integration runtimeはtickできません")
        require_aware(observed_at, "observed_at")
        require_identifier(frame_id, "frame_id")
        require_identifier(trace_id, "trace_id")
        self._reap_retired_tasks()

        report_before = self._controller.execution_report
        if report_before.status in {
            BodyMotionExecutionStatus.STARTED,
            BodyMotionExecutionStatus.OBSERVABLE,
        }:
            self._consume_planning_result(observed_at, monotonic_now_s)

        result = self._controller.tick(
            observed_at=observed_at,
            monotonic_now_s=monotonic_now_s,
            active_support_contact_ids=active_support_contact_ids,
            overlay_bundle=self._latest_overlay,
            frame_id=frame_id,
            trace_id=trace_id,
        )
        self._frame_buffer.publish(result.frame)
        self._project_execution_report(result)

        if report_before.status is BodyMotionExecutionStatus.PLANNED:
            self._consume_planning_result(observed_at, monotonic_now_s)
        else:
            self._consume_failed_planning_result(observed_at)
        return result

    async def close(self, *, observed_at: datetime) -> None:
        require_aware(observed_at, "observed_at")
        if self._closed:
            return
        self._closed = True
        tasks: list[asyncio.Task[BodyMotionPlan]] = []
        if self._planning_task is not None:
            if not self._planning_task.done():
                self._planning_task.cancel()
            tasks.append(self._planning_task)
            if self._planning_submission is not None:
                self._terminalize_planning_session(
                    self._planning_submission.session_id,
                    BodyExecutionSessionStatus.CANCELLED,
                    observed_at,
                    "shutdown_cancelled",
                )
        for _, task in self._retired_tasks:
            if not task.done():
                task.cancel()
            tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._realtime_runtime is not None:
            await self._realtime_runtime.close()

        report = self._controller.execution_report
        if report.status in {
            BodyMotionExecutionStatus.STARTED,
            BodyMotionExecutionStatus.OBSERVABLE,
        }:
            interrupted = self._controller.interrupt(observed_at)
            active = self.active_session
            if active is not None and active.status not in {
                BodyExecutionSessionStatus.COMPLETED,
                BodyExecutionSessionStatus.CANCELLED,
                BodyExecutionSessionStatus.SUPERSEDED,
                BodyExecutionSessionStatus.REJECTED,
                BodyExecutionSessionStatus.FAILED,
            }:
                self._sessions[active.session_id] = replace(
                    active,
                    status=BodyExecutionSessionStatus.CANCELLED,
                    current_body_state_revision=self._authority.current.revision,
                    started_at=interrupted.started_at,
                    completed_at=interrupted.completed_at,
                    terminal_reason="shutdown_cancelled",
                )
        self._planning_task = None
        self._planning_submission = None
        self._retired_tasks.clear()

    def _trace_for(self, submission: BodyPlanningSubmission) -> BodyIntegrationTrace:
        snapshot = submission.snapshot
        revisions = snapshot.intent.revisions
        return BodyIntegrationTrace(
            snapshot.trace_id,
            snapshot.intent.decision_id,
            snapshot.intent.intent_id,
            submission.command_id,
            None,
            snapshot.body_model.body_model_id,
            revisions.source_context_revision,
            revisions.goal_revision,
            revisions.attention_revision,
            snapshot.body_state.revision,
            snapshot.expression.revision,
            submission.created_at,
        )

    def _terminalize_planning_session(
        self,
        session_id: str,
        status: BodyExecutionSessionStatus,
        completed_at: datetime,
        reason: str,
    ) -> None:
        current = self._sessions.get(session_id)
        if current is None:
            return
        if current.status in {
            BodyExecutionSessionStatus.COMPLETED,
            BodyExecutionSessionStatus.CANCELLED,
            BodyExecutionSessionStatus.SUPERSEDED,
            BodyExecutionSessionStatus.REJECTED,
            BodyExecutionSessionStatus.FAILED,
        }:
            return
        self._sessions[session_id] = replace(
            current,
            status=status,
            current_body_state_revision=self._authority.current.revision,
            completed_at=completed_at,
            terminal_reason=reason,
        )

    def _consume_planning_result(self, observed_at: datetime, monotonic_now_s: float) -> None:
        task = self._planning_task
        submission = self._planning_submission
        if task is None or submission is None or not task.done():
            return
        if task.cancelled():
            self._terminalize_planning_session(
                submission.session_id,
                BodyExecutionSessionStatus.CANCELLED,
                observed_at,
                "planning_cancelled",
            )
            self._clear_current_planning()
            return
        error = task.exception()
        if error is not None:
            self._terminalize_planning_session(
                submission.session_id,
                BodyExecutionSessionStatus.FAILED,
                observed_at,
                f"planning_failed:{type(error).__name__}",
            )
            self._clear_current_planning()
            return
        plan = task.result()
        if (
            plan.plan_id != submission.plan_id
            or plan.candidate.source_decision_id != submission.snapshot.intent.decision_id
            or plan.candidate.source_intent_id != submission.snapshot.intent.intent_id
        ):
            self._terminalize_planning_session(
                submission.session_id,
                BodyExecutionSessionStatus.REJECTED,
                observed_at,
                "planning_result_identity_mismatch",
            )
            self._clear_current_planning()
            return

        trajectory = compile_body_motion_plan(
            plan,
            self._model,
            self._authority.current,
            self._solver_policy,
            trajectory_id=submission.trajectory_id,
            duration_s=submission.trajectory_duration_s,
        )
        old_report = self._controller.supersede_trajectory(
            trajectory,
            observed_at=observed_at,
            started_monotonic_s=monotonic_now_s,
        )
        active = self.active_session
        if active is not None and old_report.status is BodyMotionExecutionStatus.SUPERSEDED:
            self._sessions[active.session_id] = replace(
                active,
                status=BodyExecutionSessionStatus.SUPERSEDED,
                current_body_state_revision=self._authority.current.revision,
                started_at=old_report.started_at,
                completed_at=old_report.completed_at,
                terminal_reason="trajectory_superseded",
            )

        current = self._sessions[submission.session_id]
        trace = replace(current.trace, motion_plan_id=plan.plan_id)
        ready = replace(
            current,
            trace=trace,
            status=BodyExecutionSessionStatus.PLAN_READY,
            active_plan_id=plan.plan_id,
            current_body_state_revision=self._authority.current.revision,
        )
        self._sessions[submission.session_id] = ready
        self._active_session_id = submission.session_id
        self._clear_current_planning()

    def _consume_failed_planning_result(self, observed_at: datetime) -> None:
        task = self._planning_task
        submission = self._planning_submission
        if task is None or submission is None or not task.done():
            return
        if task.cancelled() or task.exception() is not None:
            self._consume_planning_result(observed_at, 0.0)

    def _project_execution_report(self, result: BodyControllerTickResult) -> None:
        active = self.active_session
        if active is None:
            return
        report = result.execution_report
        if report.plan_id != active.active_plan_id:
            return
        if report.status in {
            BodyMotionExecutionStatus.STARTED,
            BodyMotionExecutionStatus.OBSERVABLE,
        }:
            self._sessions[active.session_id] = replace(
                active,
                status=BodyExecutionSessionStatus.EXECUTING,
                current_body_state_revision=result.frame.body_state_revision,
                started_at=report.started_at,
            )
        elif report.status is BodyMotionExecutionStatus.COMPLETED:
            self._sessions[active.session_id] = replace(
                active,
                status=BodyExecutionSessionStatus.COMPLETED,
                current_body_state_revision=result.frame.body_state_revision,
                started_at=report.started_at,
                completed_at=report.completed_at,
                terminal_reason="trajectory_completed",
            )

    def _clear_current_planning(self) -> None:
        self._planning_task = None
        self._planning_submission = None

    def _reap_retired_tasks(self) -> None:
        remaining: list[tuple[int, asyncio.Task[BodyMotionPlan]]] = []
        for generation, task in self._retired_tasks:
            if task.done():
                if not task.cancelled():
                    task.exception()
                continue
            remaining.append((generation, task))
        self._retired_tasks = remaining
