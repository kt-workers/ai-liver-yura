from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.domain.activities import Activity, ActivityResult, ActivityType
from app.domain.behavior import (
    ActivityOperation,
    ActivityPlan,
    ActivityPlanEvaluation,
    BehaviorDecision,
    BehaviorPlanningContext,
    SituationAnalysis,
    SpeechAct,
)
from app.domain.body_instruction import (
    BodyConstraintExecutionResult,
    BodyConstraintExecutionStatus,
    BodyInstruction,
)
from app.domain.body_pose_dynamics import BodyExternalConstraint, BodyPoseAxis
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.domain.events import AgentEvent, AgentEventType
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)
from app.prompting.body_aware_input_meaning_prompt_builder import (
    BodyAwareInputMeaningPromptBuilder,
)
from app.runtime.behavior_planning_context_builder import (
    BehaviorPlanningPreparation,
)
from app.runtime.behavior_routing_coordinator import BehaviorRoutingCoordinator
from app.runtime.body_aware_behavior_planner import BodyAwareBehaviorPlanner
from app.runtime.body_aware_response_validation import BodyAwareResponseValidator
from app.runtime.body_instruction_constraint_resolver import (
    BodyInstructionConstraintResolver,
)
from app.runtime.body_instruction_executor import BodyInstructionExecutor
from app.runtime.cognitive_direction_parsers import InputMeaningJsonParser


def _meaning_payload(body_instruction: dict[str, object] | None) -> dict[str, object]:
    return {
        "input_speech_act": "command",
        "primary_intent": "direct_body_action",
        "expected_response": "action",
        "target": {"type": "agent_body", "id": "explicit_body_direction"},
        "body_instruction": body_instruction,
        "entities": [],
        "references": [],
        "information_provided": [],
        "negated": False,
        "hypothetical": False,
        "past_reference": False,
        "conversation_phase_signal": "continue",
        "confidence": 0.97,
        "reason": "explicit body direction",
    }


def _analysis(instruction: BodyInstruction) -> SituationAnalysis:
    return SituationAnalysis(
        activity_candidate=None,
        operation=ActivityOperation.DISCUSS,
        goal="明示Body指示へ応答する",
        constraints={
            "_internal_directive": {
                "structured_input_meaning": {
                    **_meaning_payload(instruction.as_context()),
                },
                "internal_directive": {
                    "response_mode": "react",
                    "question_budget": 0,
                    "new_direction_budget": 0,
                },
            },
            "_interaction_intention": InteractionIntention(
                intention=InteractionIntentionType.ACT,
                confidence=0.98,
                source="test",
                reason="explicit_body_instruction",
                activity_type=None,
                observation_only=True,
            ).as_context(),
        },
        speech_act=SpeechAct.COMMAND,
        confidence=0.97,
        reason="input_meaning_and_internal_directive_separated",
        evaluator_type="llm",
    )


def _planning_context(text: str) -> BehaviorPlanningContext:
    return BehaviorPlanningContext(
        user_text=text,
        source_event_id="event-body-command",
        available_capabilities=frozenset(),
        authority_role="user",
        instruction_trusted=False,
        activity_definitions=(),
    )


def test_input_meaning_parser_preserves_semantic_body_instruction() -> None:
    raw = json.dumps(
        _meaning_payload(
            {
                "effector": "arm",
                "direction": "up",
                "side": "right",
                "magnitude": 0.9,
            }
        ),
        ensure_ascii=False,
    )

    meaning = InputMeaningJsonParser().parse(raw, source_text="右手挙げて")

    assert meaning is not None
    assert meaning.body_instruction == BodyInstruction(
        effector="arm",
        direction="up",
        side="right",
        magnitude=0.9,
    )
    assert meaning.as_context()["body_instruction"] == {
        "effector": "arm",
        "direction": "up",
        "side": "right",
        "magnitude": 0.9,
    }


def test_body_aware_input_prompt_requests_semantics_not_motion_names() -> None:
    prompt = BodyAwareInputMeaningPromptBuilder().build(
        {
            "event": {
                "type": "user_text",
                "source_event_id": "event-1",
                "user_text": "右見て",
            }
        }
    )

    assert "body_instruction" in prompt
    assert "effector" in prompt
    assert "direction" in prompt
    assert "モーション名ではない" in prompt
    assert "『右見て』はhead/right" in prompt


def test_resolver_maps_right_look_to_temporary_head_and_gaze_axes() -> None:
    resolution = BodyInstructionConstraintResolver().resolve(
        BodyInstruction("head", "right", magnitude=0.8)
    )

    assert resolution.constraint is not None
    targets = {target.axis: target.value for target in resolution.constraint.targets}
    assert targets[BodyPoseAxis.HEAD_YAW] > 0.0
    assert targets[BodyPoseAxis.GAZE_X] > 0.0
    assert resolution.constraint.duration_ms <= 2000


def test_resolver_maps_right_arm_raise_without_motion_preset() -> None:
    resolution = BodyInstructionConstraintResolver().resolve(
        BodyInstruction("arm", "up", side="right", magnitude=0.9)
    )

    assert resolution.constraint is not None
    assert tuple(target.axis for target in resolution.constraint.targets) == (
        BodyPoseAxis.RIGHT_ARM_RAISE,
    )
    assert resolution.constraint.targets[0].value >= 0.9


def test_body_aware_planner_uses_runtime_body_activity_when_registry_is_empty() -> None:
    planner = BodyAwareBehaviorPlanner(situation_evaluator=MagicMock())
    instruction = BodyInstruction("head", "right", magnitude=0.8)

    plan = planner.plan_from_analysis(_planning_context("右見て"), _analysis(instruction))

    assert plan.decision is BehaviorDecision.START_ACTIVITY
    assert plan.activity_type == ActivityType.BODY_EXPRESSION_LOOP.value
    assert plan.provider_plugin_id == "runtime"
    assert plan.required_capability is None
    assert plan.constraints["_body_instruction"] == instruction.as_context()


def test_viewer_body_direction_is_not_promoted_to_runtime_execution() -> None:
    planner = BodyAwareBehaviorPlanner(situation_evaluator=MagicMock())
    instruction = BodyInstruction("head", "right", magnitude=0.8)
    context = _planning_context("右見て")
    context = BehaviorPlanningContext(
        **{
            **context.__dict__,
            "authority_role": "viewer",
        }
    ) if hasattr(context, "__dict__") else BehaviorPlanningContext(
        user_text=context.user_text,
        source_event_id=context.source_event_id,
        available_capabilities=context.available_capabilities,
        authority_role="viewer",
        activity_definitions=(),
    )

    plan = planner.plan_from_analysis(context, _analysis(instruction))

    assert plan.activity_type == "conversation"


class _RecordingBody:
    def __init__(self) -> None:
        self.constraints: list[BodyExternalConstraint] = []

    async def apply_external_constraint(
        self,
        constraint: BodyExternalConstraint,
    ) -> BodyConstraintExecutionResult:
        self.constraints.append(constraint)
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.APPLIED,
            constraint_id=constraint.constraint_id,
            reason="body_constraint_applied",
            target_axes=tuple(target.axis.value for target in constraint.targets),
        )


@pytest.mark.asyncio
async def test_executor_returns_applied_result_separate_from_speech() -> None:
    body = _RecordingBody()
    executor = BodyInstructionExecutor(body_provider=lambda: cast(Any, body))

    result = await executor.execute(
        BodyInstruction("arm", "up", side="right", magnitude=0.9)
    )

    assert result.status is BodyConstraintExecutionStatus.APPLIED
    assert result.applied is True
    assert result.target_axes == (BodyPoseAxis.RIGHT_ARM_RAISE.value,)
    assert len(body.constraints) == 1


@pytest.mark.asyncio
async def test_executor_reports_unsupported_when_body_is_disconnected() -> None:
    result = await BodyInstructionExecutor(body_provider=lambda: None).execute(
        BodyInstruction("head", "right", magnitude=0.8)
    )

    assert result.status is BodyConstraintExecutionStatus.UNSUPPORTED
    assert result.applied is False
    assert result.reason == "body_subsystem_unavailable"


class _StubPlanner:
    def __init__(self, analysis: SituationAnalysis, plan: ActivityPlan) -> None:
        self.analysis = analysis
        self.plan_value = plan

    async def evaluate_situation(self, context: BehaviorPlanningContext) -> SituationAnalysis:
        return self.analysis

    async def plan(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> ActivityPlan:
        return self.plan_value

    def fallback_after_rejection(self, evaluation: ActivityPlanEvaluation) -> ActivityPlan:
        raise AssertionError("accepted runtime body plan must not use rejection fallback")


class _StubValidator:
    def validate(self, plan: ActivityPlan) -> ActivityPlanEvaluation:
        return ActivityPlanEvaluation(
            plan=plan,
            accepted=True,
            result=ActivityResult(
                result_type="activity_plan_accepted",
                summary="runtime body activity accepted",
            ),
        )


class _StubContextBuilder:
    def __init__(self, context: BehaviorPlanningContext) -> None:
        self.context = context

    def build(self, event: AgentEvent) -> BehaviorPlanningPreparation:
        return BehaviorPlanningPreparation(
            event=event,
            context=self.context,
            ongoing_activity=None,
        )


class _FailingFallback:
    def with_plugin_availability(self, event: AgentEvent) -> AgentEvent:
        raise AssertionError("runtime body activity must bypass conversation fallback")

    def with_execution_fallback(self, *args: object, **kwargs: object) -> AgentEvent:
        raise AssertionError("runtime body activity must bypass execution fallback")


class _AppliedBodyInstructionExecutor:
    def __init__(self) -> None:
        self.instructions: list[BodyInstruction] = []

    async def execute(self, instruction: BodyInstruction) -> BodyConstraintExecutionResult:
        self.instructions.append(instruction)
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.APPLIED,
            constraint_id="constraint-test",
            reason="body_constraint_applied",
            target_axes=(BodyPoseAxis.HEAD_YAW.value, BodyPoseAxis.GAZE_X.value),
        )


@pytest.mark.asyncio
async def test_behavior_routing_records_body_execution_result_without_conversation_fallback() -> None:
    instruction = BodyInstruction("head", "right", magnitude=0.8)
    analysis = _analysis(instruction)
    planner = BodyAwareBehaviorPlanner(situation_evaluator=MagicMock())
    plan = planner.plan_from_analysis(_planning_context("右見て"), analysis)
    body_executor = _AppliedBodyInstructionExecutor()
    coordinator = BehaviorRoutingCoordinator(
        planner=cast(Any, _StubPlanner(analysis, plan)),
        validator=cast(Any, _StubValidator()),
        plugin_manager=cast(Any, object()),
        context_builder=cast(Any, _StubContextBuilder(_planning_context("右見て"))),
        confirmation_coordinator=None,
        plugin_activity_coordinator=cast(Any, object()),
        activity_switch_coordinator=cast(Any, object()),
        fallback_router=cast(Any, _FailingFallback()),
        trace_logger=cast(Any, MagicMock()),
        body_instruction_executor=cast(Any, body_executor),
    )
    event = AgentEvent(
        AgentEventType.USER_TEXT,
        payload={"text": "右見て"},
    )

    routed = await coordinator.route(event)

    assert routed is not None
    execution = routed.payload["activity_execution_result"]
    assert execution.status is ActivityExecutionStatus.SUCCEEDED
    assert routed.payload["execution_performed"] is True
    assert body_executor.instructions == [instruction]


def _act_context(*, status: ActivityExecutionStatus, activity_type: str) -> ResponseContext:
    intention = InteractionIntention(
        intention=InteractionIntentionType.ACT,
        confidence=0.98,
        source="test",
        reason="explicit_body_instruction",
        activity_type=ActivityType.BODY_EXPRESSION_LOOP.value,
        observation_only=True,
    )
    return ResponseContext(
        user_input="右見て",
        activity_type=activity_type,
        operation="start",
        status=status,
        failure_reason=None,
        result_summary="",
        allowed_claims=(
            ResponseClaim.ACTIVITY_SUCCEEDED,
            ResponseClaim.CONVERSATION_ONLY,
        ),
        forbidden_claims=(
            ResponseClaim.ACTIVITY_COMPLETED,
            ResponseClaim.EXTERNAL_RESULT_OBTAINED,
        ),
        activity_goal="身体方向を一時制約として適用する",
        memory={"interaction_intention": intention.as_context()},
    )


@pytest.mark.asyncio
async def test_present_progressive_body_claim_is_rejected_without_execution_result() -> None:
    validator = BodyAwareResponseValidator()
    source = Activity(ActivityType.BEHAVIOR_PLANNING, "respond")
    context = _act_context(
        status=ActivityExecutionStatus.WAITING_INPUT,
        activity_type="conversation",
    )
    response = CharacterResponse(
        speech="了解、右を見てるよ。",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
    )

    result = await validator.validate(source, context, response)

    assert result.accepted is False
    assert "activity_succeeded" in result.reason


@pytest.mark.asyncio
async def test_present_progressive_body_claim_is_allowed_after_body_apply_success() -> None:
    validator = BodyAwareResponseValidator()
    source = Activity(ActivityType.BEHAVIOR_PLANNING, "respond")
    context = _act_context(
        status=ActivityExecutionStatus.SUCCEEDED,
        activity_type=ActivityType.BODY_EXPRESSION_LOOP.value,
    )
    response = CharacterResponse(
        speech="うん、右手を挙げてるよ。",
        claims=(ResponseClaim.ACTIVITY_SUCCEEDED,),
    )

    result = await validator.validate(source, context, response)

    assert result.accepted is True
