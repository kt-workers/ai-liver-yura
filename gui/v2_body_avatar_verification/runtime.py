from __future__ import annotations

import asyncio
import math
import os
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from app.adapters.llm.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesModelPolicy,
    OpenAIResponsesRoleConfig,
)
from app.domain.body import AnatomicalRegion, AnatomicalSide, Axis
from app.domain.body_expression import (
    BodyExpressionAxis,
    BodyExpressionAxisValue,
    BodyExpressionContext,
    BodyFocusExpressionConstraint,
    NormalizedExpressionValue,
)
from app.domain.body_integration import BodyIntegrationRuntime, BodyPlanningSubmission
from app.domain.body_motion_planning import (
    BodyBalanceMode,
    BodyMotionEffect,
    BodyMotionGoal,
    BodyMotionIntentView,
    BodyMotionPhase,
    BodyMotionPlan,
    BodyMotionPlanAuthority,
    BodyMotionPlanner,
    BodyMotionPlanningCommitState,
    BodyMotionPlanningContextSnapshot,
    BodyMotionPlanningPolicy,
    BodyMotionSelector,
    BodySpatialTarget,
    BodySpatialTargetKind,
    DeterministicBodyMotionPlanner,
    DeterministicBodyPlanningDirective,
)
from app.domain.body_motion_planning.planner import (
    INPUT_SCHEMA as BODY_MOTION_INPUT_SCHEMA,
    OUTPUT_SCHEMA as BODY_MOTION_OUTPUT_SCHEMA,
    ROLE_ID as BODY_MOTION_ROLE_ID,
)
from app.domain.body_realtime import (
    ChannelOverlay,
    RealtimeChannel,
    RealtimeLayer,
    RealtimeLayerState,
    RealtimeLayerStatus,
    RealtimeOverlayBundle,
)
from app.domain.body_solver import (
    BodyContinuousController,
    BodyPoseFrame,
    BodyStateAuthority,
    LatestBodyFrameBuffer,
    v2_baseline_body_solver_policy,
)
from app.domain.contracts import RevisionVector
from app.domain.executive import ExecutiveInterruptibility, ExecutivePriority
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMFailurePolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRequestRetryPolicy,
)
from app.subsystems.avatar import (
    AvatarCapabilityView,
    AvatarChannelBinding,
    AvatarJointBinding,
    AvatarMirrorPolicy,
    AvatarModelBinding,
    AvatarModelKind,
    AvatarPresentationRuntime,
    StickAvatarRenderer,
)
from tests.domain.body_solver.d10_fixtures import (
    SUPPORT_CONTACT_IDS,
    StaticTargetResolver,
    physical_model,
    physical_state,
    position_snapshot,
    reach_task,
    trajectory_for,
)

ALL_AXES = (Axis.X, Axis.Y, Axis.Z)
SIGNED_CHANNELS = {
    RealtimeChannel.GAZE_X,
    RealtimeChannel.GAZE_Y,
    RealtimeChannel.MOUTH_ROUNDNESS,
    RealtimeChannel.SUBTLE_SWAY,
}


@dataclass(frozen=True, slots=True)
class PlannerRequestOptions:
    mode: str
    delay_seconds: float


class _LivePlanningState:
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


class VerificationPlanner:
    """検証要求ごとに決定論経路と実Provider経路を同じAuthority gateへ接続する。"""

    def __init__(self, live_state: _LivePlanningState) -> None:
        self._live_state = live_state
        self._plan_authority = BodyMotionPlanAuthority()
        self._options: dict[str, PlannerRequestOptions] = {}
        self._lock = threading.Lock()
        self._status = "idle"
        self._request_id: str | None = None
        self._last_latency_ms: float | None = None
        self._last_error: str | None = None
        self._last_plan: dict[str, object] | None = None
        self._live_planner: BodyMotionPlanner | None = None

    def register(self, request_id: str, *, mode: str, delay_seconds: float) -> None:
        if mode not in {"deterministic", "live_llm"}:
            raise ValueError("modeが不正です")
        if not math.isfinite(delay_seconds) or delay_seconds < 0 or delay_seconds > 30:
            raise ValueError("delay_secondsが不正です")
        with self._lock:
            self._options[request_id] = PlannerRequestOptions(mode, float(delay_seconds))

    def diagnostics(self) -> dict[str, object]:
        with self._lock:
            return {
                "status": self._status,
                "request_id": self._request_id,
                "last_latency_ms": self._last_latency_ms,
                "last_error": self._last_error,
                "last_plan": self._last_plan,
            }

    async def plan(
        self,
        snapshot: BodyMotionPlanningContextSnapshot,
        *,
        candidate_id: str,
        plan_id: str,
        created_at: datetime,
    ) -> BodyMotionPlan:
        with self._lock:
            options = self._options.get(
                snapshot.request_id, PlannerRequestOptions("deterministic", 0.0)
            )
            self._status = "waiting"
            self._request_id = snapshot.request_id
            self._last_error = None
        started = time.monotonic()
        try:
            if options.delay_seconds:
                await asyncio.sleep(options.delay_seconds)
            with self._lock:
                self._status = "provider" if options.mode == "live_llm" else "planning"
            if options.mode == "live_llm":
                planner = self._live_planner or self._build_live_planner()
                self._live_planner = planner
                plan = await planner.plan(
                    snapshot,
                    candidate_id=candidate_id,
                    plan_id=plan_id,
                    created_at=created_at,
                )
            else:
                plan = await DeterministicBodyMotionPlanner(
                    self._live_state, self._plan_authority
                ).plan(
                    snapshot,
                    candidate_id=candidate_id,
                    plan_id=plan_id,
                    created_at=created_at,
                )
            with self._lock:
                self._status = "completed"
                self._last_latency_ms = (time.monotonic() - started) * 1000.0
                self._last_plan = _plan_summary(plan)
            return plan
        except BaseException as error:
            with self._lock:
                self._status = "cancelled" if isinstance(error, asyncio.CancelledError) else "failed"
                self._last_latency_ms = (time.monotonic() - started) * 1000.0
                self._last_error = f"{type(error).__name__}: {error}"
            raise
        finally:
            with self._lock:
                self._options.pop(snapshot.request_id, None)

    def _build_live_planner(self) -> BodyMotionPlanner:
        model_name = os.environ.get("YURA_VERIFY_OPENAI_MODEL", "").strip()
        if not model_name:
            raise ValueError("YURA_VERIFY_OPENAI_MODELが設定されていません")
        execution = LLMExecutionPolicy(
            "verification.body_motion",
            1,
            LLMModelClass.BALANCED,
            LLMReasoningEffort.MEDIUM,
            60.0,
            1,
            3000,
            LLMRequestRetryPolicy(0.25, 2.0, 1.0),
        )
        role_config = OpenAIResponsesRoleConfig(
            role_id=BODY_MOTION_ROLE_ID,
            model_policies={
                LLMModelClass.BALANCED: OpenAIResponsesModelPolicy(
                    "verification.body_motion.openai",
                    1,
                    model_name,
                    {LLMReasoningEffort.MEDIUM: "medium"},
                    provider_max_output_tokens=3000,
                )
            },
            input_schema_id=BODY_MOTION_INPUT_SCHEMA,
            output_schema_id=BODY_MOTION_OUTPUT_SCHEMA,
            provider_output_format_name="body_motion_verification_v1",
            output_json_schema=body_motion_candidate_output_schema(),
            instructions=body_motion_candidate_instructions(),
            failure_policy=LLMFailurePolicy.FAIL_CLOSED,
        )
        adapter = OpenAIResponsesAdapter.from_environment((role_config,))
        return BodyMotionPlanner(
            adapter,
            self._live_state,
            self._plan_authority,
            BodyMotionPlanningPolicy(execution),
        )


def body_motion_candidate_instructions() -> str:
    return (
        "入力はExecutive確定済みの身体運動コンテキストです。"
        "出力はbody.motion-planning.candidate.v1のJSONだけにしてください。"
        "request_id、source decision/intent、revision、body_model_id、planning body/expression revision、"
        "constraintは入力を正確に保持してください。"
        "D10検証では右腕のTRANSLATEを使い、selectorはregion=arm、side=right、"
        "chain_ids=[\"chain:arm\"]、end_effector_joint_ids=[\"arm\"]としてください。"
        "target_refは入力intent.target_refだけを使ってください。"
        "renderer名、preset名、final joint angle、frame列、raw user textは生成しないでください。"
        "phasesは少なくとも1つ作り、stable_support_requiredを使ってください。"
    )


def body_motion_candidate_output_schema() -> dict[str, object]:
    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    nullable_vector = {
        "anyOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "required": ["x", "y", "z"],
            },
            {"type": "null"},
        ]
    }
    selector = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "region": {
                "anyOf": [
                    {"type": "string", "enum": [item.value for item in AnatomicalRegion]},
                    {"type": "null"},
                ]
            },
            "side": {
                "anyOf": [
                    {"type": "string", "enum": [item.value for item in AnatomicalSide]},
                    {"type": "null"},
                ]
            },
            "chain_ids": {"type": "array", "items": {"type": "string"}},
            "end_effector_joint_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["region", "side", "chain_ids", "end_effector_joint_ids"],
    }
    spatial_target = {
        "anyOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [item.value for item in BodySpatialTargetKind],
                    },
                    "direction": nullable_vector,
                    "target_ref": nullable_string,
                    "extent": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["kind", "direction", "target_ref", "extent"],
            },
            {"type": "null"},
        ]
    }
    constraint = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "constraint_id": {"type": "string"},
            "kind": {"type": "string"},
            "source_owner": {"type": "string"},
            "source_ref": {"type": "string"},
            "source_revision": {"type": "integer", "minimum": 0},
            "semantic_description": {"type": "string"},
            "subject_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "constraint_id",
            "kind",
            "source_owner",
            "source_ref",
            "source_revision",
            "semantic_description",
            "subject_refs",
        ],
    }
    goal = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "goal_id": {"type": "string"},
            "effect": {"type": "string", "enum": [item.value for item in BodyMotionEffect]},
            "selector": selector,
            "spatial_target": spatial_target,
            "intensity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "constraint_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "goal_id",
            "effect",
            "selector",
            "spatial_target",
            "intensity",
            "constraint_refs",
        ],
    }
    phase = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "phase_id": {"type": "string"},
            "goal_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "relative_duration_weight": {"type": "number", "exclusiveMinimum": 0.0},
            "balance_mode": {"type": "string", "enum": [item.value for item in BodyBalanceMode]},
            "expression_binding_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "phase_id",
            "goal_ids",
            "relative_duration_weight",
            "balance_mode",
            "expression_binding_ids",
        ],
    }
    coordination = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "coordination_id": {"type": "string"},
            "goal_ids": {"type": "array", "minItems": 2, "items": {"type": "string"}},
            "mode": {"type": "string"},
        },
        "required": ["coordination_id", "goal_ids", "mode"],
    }
    expression_binding = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "binding_id": {"type": "string"},
            "axis": {"type": "string", "enum": [item.value for item in BodyExpressionAxis]},
            "influence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["binding_id", "axis", "influence"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidate_id": {"type": "string"},
            "request_id": {"type": "string"},
            "source_decision_id": {"type": "string"},
            "source_intent_id": {"type": "string"},
            "revisions": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source_context_revision": {"type": "integer", "minimum": 0},
                    "goal_revision": {"type": "integer", "minimum": 0},
                    "attention_revision": {"type": "integer", "minimum": 0},
                },
                "required": [
                    "source_context_revision",
                    "goal_revision",
                    "attention_revision",
                ],
            },
            "body_model_id": {"type": "string"},
            "planning_body_state_revision": {"type": "integer", "minimum": 0},
            "planning_expression_revision": {"type": "integer", "minimum": 0},
            "planning_constraints": {"type": "array", "items": constraint},
            "goals": {"type": "array", "minItems": 1, "items": goal},
            "phases": {"type": "array", "minItems": 1, "items": phase},
            "coordination_constraints": {"type": "array", "items": coordination},
            "expression_bindings": {"type": "array", "items": expression_binding},
        },
        "required": [
            "candidate_id",
            "request_id",
            "source_decision_id",
            "source_intent_id",
            "revisions",
            "body_model_id",
            "planning_body_state_revision",
            "planning_expression_revision",
            "planning_constraints",
            "goals",
            "phases",
            "coordination_constraints",
            "expression_bindings",
        ],
    }


def _plan_summary(plan: BodyMotionPlan) -> dict[str, object]:
    candidate = plan.candidate
    return {
        "plan_id": plan.plan_id,
        "candidate_id": candidate.candidate_id,
        "goals": [
            {
                "goal_id": goal.goal_id,
                "effect": goal.effect.value,
                "region": None if goal.selector.region is None else goal.selector.region.value,
                "side": None if goal.selector.side is None else goal.selector.side.value,
                "chain_ids": list(goal.selector.chain_ids),
                "end_effector_joint_ids": list(goal.selector.end_effector_joint_ids),
                "target_ref": (
                    None if goal.spatial_target is None else goal.spatial_target.target_ref
                ),
            }
            for goal in candidate.goals
        ],
        "phase_count": len(candidate.phases),
    }


def _expression(revision: int, at: datetime) -> BodyExpressionContext:
    return BodyExpressionContext(
        revision,
        revision,
        revision,
        revision,
        revision,
        revision,
        "generic",
        1,
        1,
        "verification.body-expression",
        1,
        tuple(
            BodyExpressionAxisValue(axis, NormalizedExpressionValue(0.0))
            for axis in BodyExpressionAxis
        ),
        BodyFocusExpressionConstraint(None, None, (), None, None),
        (),
        (),
        (),
        at,
    )


def _avatar_binding(at: datetime) -> AvatarModelBinding:
    channels = tuple(RealtimeChannel)
    channel_bindings = tuple(
        AvatarChannelBinding(
            channel,
            f"renderer:{channel.value}",
            output_min=-1.0 if channel in SIGNED_CHANNELS else 0.0,
            output_max=1.0,
        )
        for channel in channels
    )
    return AvatarModelBinding(
        "binding:verification-stick",
        1,
        1,
        AvatarModelKind.STICK,
        "model:verification-stick-d10",
        "body.d10",
        "root",
        (
            AvatarJointBinding("root", "renderer:root", True, True, ALL_AXES, ALL_AXES),
            AvatarJointBinding("arm", "renderer:arm", True, True, ALL_AXES, ALL_AXES),
        ),
        channel_bindings,
        AvatarMirrorPolicy.NONE,
        AvatarCapabilityView(
            ("root", "arm"),
            channels,
            ALL_AXES,
            ALL_AXES,
            60.0,
            True,
            True,
            True,
        ),
        at,
    )


class VerificationEngine:
    """#341/#346の検証専用runtime。Browserはsnapshotを読むだけである。"""

    def __init__(self, *, tick_hz: float = 30.0) -> None:
        if not math.isfinite(tick_hz) or tick_hz <= 0:
            raise ValueError("tick_hzが不正です")
        self._tick_hz = float(tick_hz)
        self._commands: queue.Queue[dict[str, object]] = queue.Queue()
        self._snapshot_lock = threading.Lock()
        self._snapshot: dict[str, object] = {
            "ready": False,
            "frame_count": 0,
            "fatal_error": None,
        }
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._runtime: BodyIntegrationRuntime | None = None
        self._authority: BodyStateAuthority | None = None
        self._planner: VerificationPlanner | None = None
        self._resolver: StaticTargetResolver | None = None
        self._avatar_runtime: AvatarPresentationRuntime | None = None
        self._renderer: StickAvatarRenderer | None = None
        self._frame_count = 0
        self._request_sequence = 0
        self._gaze_x = 0.0
        self._gaze_y = 0.0
        self._mouth_openness = 0.0
        self._blink_until = 0.0
        self._target_angle = 0.35
        self._mode = "deterministic"
        self._delay_seconds = 0.0
        self._last_avatar_report: dict[str, object] | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._thread_main, name="v2-body-avatar-verify")
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def submit_command(self, command: dict[str, object]) -> None:
        self._commands.put(dict(command))

    def snapshot(self) -> dict[str, object]:
        with self._snapshot_lock:
            return cast(dict[str, object], _json_clone(self._snapshot))

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except BaseException as error:
            self._publish_fatal(error)

    async def _run(self) -> None:
        self._initialize_runtime()
        assert self._runtime is not None
        interval = 1.0 / self._tick_hz
        started = time.monotonic()
        next_tick = started
        try:
            while not self._stop.is_set():
                self._drain_commands()
                now = datetime.now(timezone.utc)
                monotonic_now = time.monotonic() - started
                self._tick(now, monotonic_now)
                next_tick += interval
                await asyncio.sleep(max(0.0, next_tick - time.monotonic()))
        finally:
            await self._runtime.close(observed_at=datetime.now(timezone.utc))
            self._publish_snapshot(datetime.now(timezone.utc), time.monotonic() - started)

    def _initialize_runtime(self) -> None:
        now = datetime.now(timezone.utc)
        model = physical_model()
        policy = v2_baseline_body_solver_policy()
        authority = BodyStateAuthority(model, physical_state())
        resolver = StaticTargetResolver(
            (position_snapshot(0.35, target_ref="target:verification:initial"),)
        )
        initial = trajectory_for(
            reach_task(target_ref="target:verification:initial"),
            plan_id="plan:verification:initial",
            trajectory_id="trajectory:verification:initial",
            solver_policy_revision=policy.policy_revision,
            duration_s=120.0,
        )
        controller = BodyContinuousController(
            model,
            policy,
            initial,
            authority,
            resolver,
            started_monotonic_s=0.0,
        )
        frame_buffer = LatestBodyFrameBuffer(model.body_model_id)
        planner = VerificationPlanner(_LivePlanningState(authority))
        runtime = BodyIntegrationRuntime(
            model,
            policy,
            authority,
            controller,
            planner,
            frame_buffer,
        )
        renderer = StickAvatarRenderer()
        avatar_runtime = AvatarPresentationRuntime(
            model,
            _avatar_binding(now),
            renderer,
        )
        self._runtime = runtime
        self._authority = authority
        self._planner = planner
        self._resolver = resolver
        self._avatar_runtime = avatar_runtime
        self._renderer = renderer
        runtime.start()
        self._publish_snapshot(now, 0.0)

    def _drain_commands(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                self._apply_command(command)
            except (ValueError, RuntimeError) as error:
                with self._snapshot_lock:
                    self._snapshot["last_command_error"] = f"{type(error).__name__}: {error}"

    def _apply_command(self, command: dict[str, object]) -> None:
        action = command.get("action")
        if action == "submit_motion":
            mode = str(command.get("mode", "deterministic"))
            delay = _bounded_float(command.get("delay_seconds", 0.0), 0.0, 30.0)
            angle = _bounded_float(command.get("target_angle", 0.35), -0.75, 0.75)
            self._submit_motion(mode=mode, delay_seconds=delay, target_angle=angle)
            return
        if action == "renderer":
            available = command.get("available")
            if type(available) is not bool:
                raise ValueError("availableが不正です")
            assert self._renderer is not None
            self._renderer.set_available(available)
            return
        if action == "channels":
            self._gaze_x = _bounded_float(command.get("gaze_x", self._gaze_x), -1.0, 1.0)
            self._gaze_y = _bounded_float(command.get("gaze_y", self._gaze_y), -1.0, 1.0)
            self._mouth_openness = _bounded_float(
                command.get("mouth_openness", self._mouth_openness), 0.0, 1.0
            )
            return
        if action == "blink":
            self._blink_until = time.monotonic() + 0.18
            return
        raise ValueError("未知のcommandです")

    def _submit_motion(self, *, mode: str, delay_seconds: float, target_angle: float) -> None:
        assert self._runtime is not None
        assert self._authority is not None
        assert self._planner is not None
        assert self._resolver is not None
        self._request_sequence += 1
        index = self._request_sequence
        now = datetime.now(timezone.utc)
        target_ref = f"target:verification:{index}"
        self._resolver.replace(
            position_snapshot(target_angle, target_ref=target_ref, generation=index + 1)
        )
        revisions = RevisionVector(index, index, index)
        intent = BodyMotionIntentView(
            f"decision:verification:{index}",
            f"intent:verification:{index}",
            "右腕を指定された対象へ滑らかに向ける",
            f"motion:verification:{index}",
            target_ref,
            (),
            (f"event:verification:{index}",),
            revisions,
            ExecutivePriority.FOREGROUND,
            ExecutiveInterruptibility.INTERRUPTIBLE,
            (),
            (),
        )
        directive: DeterministicBodyPlanningDirective | None = None
        if mode == "deterministic":
            goal_id = f"goal:verification:{index}"
            goal = BodyMotionGoal(
                goal_id,
                BodyMotionEffect.TRANSLATE,
                BodyMotionSelector(
                    AnatomicalRegion.ARM,
                    AnatomicalSide.RIGHT,
                    ("chain:arm",),
                    ("arm",),
                ),
                BodySpatialTarget(
                    BodySpatialTargetKind.TARGET_REF,
                    None,
                    target_ref,
                    1.0,
                ),
                1.0,
                (),
            )
            directive = DeterministicBodyPlanningDirective(
                (goal,),
                (
                    BodyMotionPhase(
                        f"phase:{goal_id}",
                        (goal_id,),
                        1.0,
                        BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
                    ),
                ),
                (),
                (),
            )
        snapshot = BodyMotionPlanningContextSnapshot(
            f"request:verification:{index}",
            intent,
            physical_model(),
            self._authority.current,
            _expression(index, now),
            (),
            (),
            now,
            f"trace:verification:{index}",
            directive,
        )
        self._planner.register(
            snapshot.request_id,
            mode=mode,
            delay_seconds=delay_seconds,
        )
        self._runtime.submit_planning(
            BodyPlanningSubmission(
                f"session:verification:{index}",
                f"command:verification:{index}",
                snapshot,
                f"candidate:verification:{index}",
                f"plan:verification:{index}",
                f"trajectory:verification:{index}",
                2.5,
                now,
            ),
            supersede_allowed=True,
        )
        self._target_angle = target_angle
        self._mode = mode
        self._delay_seconds = delay_seconds

    def _tick(self, now: datetime, monotonic_now: float) -> None:
        assert self._runtime is not None
        assert self._authority is not None
        assert self._avatar_runtime is not None
        assert self._renderer is not None
        self._runtime.publish_overlay(self._overlay(now, monotonic_now))
        self._frame_count += 1
        result = self._runtime.tick_physical(
            observed_at=now,
            monotonic_now_s=monotonic_now,
            active_support_contact_ids=SUPPORT_CONTACT_IDS,
            frame_id=f"frame:verification:{self._frame_count}",
            trace_id="trace:verification:runtime",
        )
        self._avatar_runtime.submit_frame(result.frame)
        report = self._avatar_runtime.present_latest(started_at=now)
        if report is not None:
            self._last_avatar_report = {
                "status": report.status.value,
                "frame_id": report.frame_id,
                "dropped_or_coalesced_frames": report.dropped_or_coalesced_frames,
                "degraded_items": list(report.degraded_items),
                "diagnostics": list(report.sanitized_diagnostics),
            }
        self._publish_snapshot(now, monotonic_now, result.frame)

    def _overlay(self, now: datetime, monotonic_now: float) -> RealtimeOverlayBundle:
        assert self._authority is not None
        eyelid = 0.04 if time.monotonic() < self._blink_until else 1.0
        breath_phase = (math.sin(monotonic_now * math.tau * 0.2) + 1.0) / 2.0
        subtle_sway = math.sin(monotonic_now * 0.8) * 0.12
        values = (
            (RealtimeLayer.GAZE, RealtimeChannel.GAZE_X, self._gaze_x),
            (RealtimeLayer.GAZE, RealtimeChannel.GAZE_Y, self._gaze_y),
            (RealtimeLayer.BLINK, RealtimeChannel.EYELID_OPENNESS, eyelid),
            (RealtimeLayer.BREATH, RealtimeChannel.BREATH_PHASE, breath_phase),
            (RealtimeLayer.BREATH, RealtimeChannel.BREATH_AMPLITUDE, 0.35),
            (
                RealtimeLayer.SPEECH_ARTICULATION,
                RealtimeChannel.MOUTH_OPENNESS,
                self._mouth_openness,
            ),
            (RealtimeLayer.SPEECH_ARTICULATION, RealtimeChannel.MOUTH_ROUNDNESS, 0.0),
            (
                RealtimeLayer.SPEECH_ARTICULATION,
                RealtimeChannel.JAW_OPENNESS,
                self._mouth_openness * 0.7,
            ),
            (RealtimeLayer.SPEECH_ARTICULATION, RealtimeChannel.LIP_CLOSURE, 0.0),
            (RealtimeLayer.SUBTLE_MOTION, RealtimeChannel.SUBTLE_SWAY, subtle_sway),
        )
        return RealtimeOverlayBundle(
            f"overlay-bundle:verification:{self._frame_count}",
            self._authority.current.revision,
            None,
            None,
            None,
            now,
            1000.0 / self._tick_hz,
            0.0,
            tuple(
                ChannelOverlay(
                    f"overlay:{channel.value}:{self._frame_count}",
                    layer,
                    channel,
                    value,
                    1.0,
                    50,
                )
                for layer, channel, value in values
            ),
            tuple(
                RealtimeLayerState(
                    layer,
                    (
                        RealtimeLayerStatus.INACTIVE_NO_SOURCE
                        if layer is RealtimeLayer.POSTURE_ASSIST
                        else RealtimeLayerStatus.ACTIVE
                    ),
                )
                for layer in RealtimeLayer
            ),
        )

    def _publish_snapshot(
        self,
        now: datetime,
        monotonic_now: float,
        frame: BodyPoseFrame | None = None,
    ) -> None:
        authority = self._authority
        runtime = self._runtime
        planner = self._planner
        renderer = self._renderer
        if authority is None or runtime is None or planner is None or renderer is None:
            return
        active = runtime.active_session
        controller_report = runtime.controller.execution_report
        command = renderer.latest_command
        frame_dict: dict[str, object] | None = None
        if frame is not None:
            frame_dict = {
                "frame_id": frame.frame_id,
                "body_state_revision": frame.body_state_revision,
                "active_plan_id": frame.active_plan_id,
                "active_trajectory_id": frame.active_trajectory_id,
                "channels": {
                    item.channel.value: item.value for item in frame.channel_values
                },
            }
        snapshot: dict[str, object] = {
            "ready": True,
            "frame_count": self._frame_count,
            "last_tick_at": now.isoformat(),
            "monotonic_seconds": monotonic_now,
            "body_state_revision": authority.current.revision,
            "controller_status": controller_report.status.value,
            "controller_plan_id": controller_report.plan_id,
            "pending_task_count": runtime.pending_task_count,
            "session": (
                None
                if active is None
                else {
                    "session_id": active.session_id,
                    "status": active.status.value,
                    "active_plan_id": active.active_plan_id,
                    "current_body_state_revision": active.current_body_state_revision,
                    "terminal_reason": active.terminal_reason,
                }
            ),
            "planner": planner.diagnostics(),
            "avatar": self._last_avatar_report,
            "projection_command": None if command is None else command.to_dict(),
            "renderer_available": renderer.available,
            "controls": {
                "mode": self._mode,
                "delay_seconds": self._delay_seconds,
                "target_angle": self._target_angle,
                "gaze_x": self._gaze_x,
                "gaze_y": self._gaze_y,
                "mouth_openness": self._mouth_openness,
            },
            "frame": frame_dict,
            "live_llm": {
                "api_key_present": bool(os.environ.get("OPENAI_API_KEY")),
                "model": os.environ.get("YURA_VERIFY_OPENAI_MODEL"),
                "ready": bool(
                    os.environ.get("OPENAI_API_KEY")
                    and os.environ.get("YURA_VERIFY_OPENAI_MODEL")
                ),
            },
            "fatal_error": None,
        }
        with self._snapshot_lock:
            previous_error = self._snapshot.get("last_command_error")
            if previous_error is not None:
                snapshot["last_command_error"] = previous_error
            self._snapshot = snapshot

    def _publish_fatal(self, error: BaseException) -> None:
        with self._snapshot_lock:
            self._snapshot = {
                **self._snapshot,
                "ready": False,
                "fatal_error": f"{type(error).__name__}: {error}",
            }


def _bounded_float(value: object, lower: float, upper: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("数値が不正です")
    number = float(value)
    if not math.isfinite(number) or not lower <= number <= upper:
        raise ValueError("数値が許容範囲外です")
    return number


def _json_clone(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_clone(item) for item in value]
    if isinstance(value, tuple):
        return [_json_clone(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_clone(item) for key, item in value.items()}
    return str(value)
