"""本番の身体計画から姿勢公開までを有限回実行し、判断結果を記録する。"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

from app.domain.body import BodyState, CanonicalBodyModel
from app.domain.body_expression import BodyExpressionContext
from app.domain.body_integration import BodyIntegrationRuntime, BodyPlanningSubmission
from app.domain.body_motion_planning import (
    BodyMotionPlan,
    BodyMotionPlanAuthority,
    BodyMotionPlanner,
    BodyMotionPlanningCommitState,
    BodyMotionPlanningContextSnapshot,
    BodyMotionPlanningPolicy,
)
from app.domain.body_realtime import (
    BodyGazeTargetView,
    BodyRealtimeEngine,
    BodyRealtimeRuntime,
    RealtimeMotionConstraintView,
    RealtimeOverlayBundle,
    RealtimeSpeechView,
    RealtimeTickInput,
)
from app.domain.body_solver import (
    BodyContinuousController,
    BodyPoseFrame,
    BodySolverPolicy,
    BodyStateAuthority,
    ExecutableBodyTrajectory,
    LatestBodyFrameBuffer,
)
from app.domain.body_solver.spatial import BodySpatialTargetSnapshot
from app.domain.contracts.common import JsonValue
from app.usecases.ports.llm import LLMRolePort

from .body import _project
from .body_avatar import BodyAvatarLabSession, BodyAvatarLabSettings
from .body_visualization import render_body_pose_sequence
from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    aware,
    positive,
)
from .llm_port import LabLLMPortFactory, ObservedLLMRolePort, resolve_port
from .runtime import LabTarget, RunContext


@dataclass(frozen=True)
class BodyRealtimeLabSettings:
    seed: int
    interval_s: float
    expression: BodyExpressionContext | None = None
    gaze_target: BodyGazeTargetView | None = None
    speech: RealtimeSpeechView | None = None
    motion_constraint: RealtimeMotionConstraintView | None = None

    def __post_init__(self) -> None:
        if type(self.seed) is not int or type(self.interval_s) not in (int, float):
            raise ValueError("実時間層の種と間隔の型が不正です")
        if not 0 < self.interval_s <= 1:
            raise ValueError("実時間層の間隔は0秒より大きく1秒以下にしてください")

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "seed": self.seed,
                "interval_s": self.interval_s,
                "expression": self.expression,
                "gaze_target": self.gaze_target,
                "speech": self.speech,
                "motion_constraint": self.motion_constraint,
            }
        )


@dataclass(frozen=True)
class BodyExecutionLabCase:
    fixture: ValidationFixture
    model: CanonicalBodyModel
    initial_state: BodyState
    initial_trajectory: ExecutableBodyTrajectory
    solver_policy: BodySolverPolicy
    planning_policy: BodyMotionPlanningPolicy
    submission: BodyPlanningSubmission
    targets: tuple[BodySpatialTargetSnapshot, ...]
    active_support_contact_ids: tuple[str, ...]
    started_at: datetime
    tick_count: int
    tick_interval_s: float
    realtime: BodyRealtimeLabSettings | None = None
    visualize: bool = False
    avatar: BodyAvatarLabSettings | None = None

    def __post_init__(self) -> None:
        if type(self.visualize) is not bool:
            raise ValueError("姿勢の可視化指定は真偽値で渡してください")
        aware(self.started_at)
        positive(self.tick_count)
        if self.avatar is not None:
            if not isinstance(self.avatar, BodyAvatarLabSettings):
                raise ValueError("描画先の検証設定が不正です")
            if any(index >= self.tick_count for index, _ in self.avatar.binding_reloads):
                raise ValueError("描画先の交換番号が実行する姿勢数を超えています")
        if (
            type(self.tick_interval_s) not in (int, float)
            or not isfinite(self.tick_interval_s)
            or self.tick_interval_s <= 0
        ):
            raise ValueError("姿勢更新の間隔は有限の正数で指定してください")
        if self.realtime is not None:
            if not isinstance(self.realtime, BodyRealtimeLabSettings):
                raise ValueError("実時間層の入力設定が不正です")
            RealtimeTickInput(
                self.initial_state,
                self.realtime.expression,
                self.realtime.gaze_target,
                self.realtime.speech,
                self.realtime.motion_constraint,
            )
        self.initial_state.validate_physical_for(self.model)
        if self.submission.snapshot.body_state != self.initial_state:
            raise ValueError("計画入力と初期身体状態が一致しません")
        if self.submission.snapshot.body_model != self.model:
            raise ValueError("計画入力と身体モデルが一致しません")
        targets = tuple(self.targets)
        if len({item.target_ref for item in targets}) != len(targets):
            raise ValueError("外界座標の参照は重複できません")
        object.__setattr__(self, "targets", targets)
        object.__setattr__(
            self, "active_support_contact_ids", tuple(self.active_support_contact_ids)
        )

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "model": self.model,
                "initial_state": self.initial_state,
                "initial_trajectory": self.initial_trajectory,
                "solver_policy": self.solver_policy,
                "planning_policy": self.planning_policy,
                "submission": self.submission,
                "targets": self.targets,
                "active_support_contact_ids": self.active_support_contact_ids,
                "started_at": self.started_at,
                "tick_count": self.tick_count,
                "visualize": self.visualize,
                "avatar": None if self.avatar is None else self.avatar.typed_inputs(),
                "tick_interval_s": self.tick_interval_s,
                "realtime": None if self.realtime is None else self.realtime.typed_inputs(),
            }
        )


class _FixtureTargets:
    def __init__(self, targets: tuple[BodySpatialTargetSnapshot, ...]) -> None:
        self._targets = {item.target_ref: item for item in targets}

    def resolve(self, target_ref: str) -> BodySpatialTargetSnapshot | None:
        return self._targets.get(target_ref)


class _LiveState:
    def __init__(self, authority: BodyStateAuthority) -> None:
        self._authority = authority

    async def current_commit_state(
        self, snapshot: BodyMotionPlanningContextSnapshot
    ) -> BodyMotionPlanningCommitState:
        return BodyMotionPlanningCommitState(
            snapshot.intent.revisions,
            snapshot.intent,
            snapshot.body_model,
            self._authority.current,
            snapshot.expression,
            snapshot.constraints,
            snapshot.capabilities,
            snapshot.intent.preconditions,
            self._authority.current.observed_at,
        )


class _ObservedPlanner:
    def __init__(self, owner: BodyMotionPlanner, context: RunContext) -> None:
        self._owner = owner
        self._context = context

    async def plan(
        self,
        snapshot: BodyMotionPlanningContextSnapshot,
        *,
        candidate_id: str,
        plan_id: str,
        created_at: datetime,
    ) -> BodyMotionPlan:
        async def plan() -> BodyMotionPlan:
            return await self._context.invoke_product(
                "body.execution.plan",
                lambda: self._owner.plan(
                    snapshot, candidate_id=candidate_id, plan_id=plan_id, created_at=created_at
                ),
            )

        return await self._context.invoke_port("body.execution.planning", plan)


def body_execution_target(
    cases: tuple[BodyExecutionLabCase, ...],
    port: LLMRolePort | LabLLMPortFactory,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("身体結合の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        # 各反復で本番所有者を新設し、入力の識別子と版をそのまま渡す。
        authority = BodyStateAuthority(case.model, case.initial_state)
        controller = BodyContinuousController(
            case.model,
            case.solver_policy,
            case.initial_trajectory,
            authority,
            _FixtureTargets(case.targets),
            started_monotonic_s=0.0,
        )
        buffer = LatestBodyFrameBuffer(case.model.body_model_id)
        planner = BodyMotionPlanner(
            ObservedLLMRolePort(
                context, resolve_port(port, context), {"body_motion_planning": "body.planning.llm"}
            ),
            _LiveState(authority),
            BodyMotionPlanAuthority(),
            case.planning_policy,
        )
        runtime = BodyIntegrationRuntime(
            case.model,
            case.solver_policy,
            authority,
            controller,
            _ObservedPlanner(planner, context),
            buffer,
        )
        latest_overlay: RealtimeOverlayBundle | None = None
        overlay_count = 0
        realtime_runtime: BodyRealtimeRuntime | None = None
        if case.realtime is not None:
            settings = case.realtime

            def read_input() -> RealtimeTickInput:
                return RealtimeTickInput(
                    authority.current,
                    settings.expression,
                    settings.gaze_target,
                    settings.speech,
                    settings.motion_constraint,
                )

            def publish_overlay(bundle: RealtimeOverlayBundle) -> None:
                nonlocal latest_overlay, overlay_count
                runtime.publish_overlay(bundle)
                latest_overlay = bundle
                overlay_count += 1

            realtime_runtime = BodyRealtimeRuntime(
                BodyRealtimeEngine(seed=settings.seed, target_interval_s=settings.interval_s),
                read_input,
                publish_overlay,
                target_interval_s=settings.interval_s,
            )
            runtime.attach_realtime_runtime(realtime_runtime)
        avatar: BodyAvatarLabSession | None = None
        rows: list[JsonValue] = []
        frames: list[BodyPoseFrame] = []
        loop = asyncio.get_running_loop()
        started = loop.time()
        observed_at = case.started_at
        try:
            if case.avatar is not None:
                avatar = BodyAvatarLabSession(case.model, case.avatar, max_reports=case.tick_count)
            runtime.start()
            runtime.submit_planning(case.submission, supersede_allowed=False)
            for index in range(case.tick_count):
                await asyncio.sleep(max(0.0, started + index * case.tick_interval_s - loop.time()))
                elapsed = loop.time() - started
                observed_at = case.started_at + timedelta(seconds=elapsed)

                async def tick(
                    observed_at: datetime = observed_at,
                    elapsed: float = elapsed,
                    index: int = index,
                ) -> JsonValue:
                    result = runtime.tick_physical(
                        observed_at=observed_at,
                        monotonic_now_s=elapsed,
                        active_support_contact_ids=case.active_support_contact_ids,
                        frame_id=f"{context.run_id}:{context.iteration}:frame:{index}",
                        trace_id=case.submission.snapshot.trace_id,
                    )
                    if avatar is not None:
                        avatar.submit(result.frame)
                    if case.visualize:
                        frames.append(result.frame)
                    return _project(
                        {
                            "elapsed_s": elapsed,
                            "latest_overlay": latest_overlay,
                            "overlay_count": overlay_count,
                            "result": result,
                            "session": runtime.session(case.submission.session_id),
                            "pending_task_count": runtime.pending_task_count,
                        }
                    )

                rows.append(await context.invoke_product("body.execution.tick", tick))
            final_session = runtime.session(case.submission.session_id)
        finally:
            try:
                await runtime.close(observed_at=observed_at)
            finally:
                if avatar is not None:
                    await avatar.close()
        return TargetObservation(
            RunStatus.COMPLETED,
            Gate.NOT_RUN,
            _project(
                {
                    "ticks": rows,
                    "avatar": None if avatar is None else avatar.observation(),
                    "visualization_html": render_body_pose_sequence(
                        case.model,
                        tuple(frames),
                        max_frames=context.policy.max_intervals,
                        max_bytes=context.policy.max_export_bytes,
                    )
                    if case.visualize
                    else None,
                    "final_state": authority.current,
                    "session_before_close": final_session,
                    "session_after_close": runtime.session(case.submission.session_id),
                    "publication": buffer.take_latest(),
                    "pending_task_count_after_close": runtime.pending_task_count,
                    "realtime": None
                    if realtime_runtime is None
                    else {
                        "overlay_count": overlay_count,
                        "late_tick_count": realtime_runtime.late_tick_count,
                        "pending_task_count_after_close": realtime_runtime.pending_task_count,
                    },
                }
            ),
        )

    return LabTarget(
        "body_execution",
        contract_revision,
        frozenset({LabMode.ADJACENT}),
        provider_policy_refs,
        provenance,
        run,
        frozenset({"body.execution.planning", "body.planning.llm"}),
        frozenset({"body.planning.llm"}),
    )
