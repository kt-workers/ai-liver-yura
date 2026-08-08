from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource, ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.body_instruction import (
    BodyConstraintExecutionResult,
    BodyConstraintExecutionStatus,
    BodyInstruction,
)
from app.domain.body_pose_dynamics import BodyPoseAxis
from app.domain.character_response import CharacterResponse
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.avatar_performance_action_planner import AvatarPerformanceActionPlanner
from app.usecases.body_aware_execute_action_usecase import BodyAwareExecuteActionUsecase


def _activity(instruction: BodyInstruction) -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="明示Body指示へ応答する",
        context={
            "event_payload": {
                "body_instruction_execution_ready": True,
                "behavior_plan": {
                    "constraints": {
                        "_body_instruction": instruction.as_context(),
                    }
                },
            }
        },
    )


def test_action_planner_emits_explicit_body_move_once_before_speech() -> None:
    instruction = BodyInstruction("arm", "up", side="right", magnitude=0.9)
    planner = AvatarPerformanceActionPlanner(cast(Any, MagicMock()))

    actions = planner._reaction_action_plans(
        _activity(instruction),
        CharacterResponse(speech="うん。", expression="neutral"),
        fallback_speech="うん。",
        output_unit_id="output-1",
        base_metadata={},
        skip_topic_memory=False,
    )

    body_moves = [
        action
        for action in actions
        if action.action_type is ActionType.MOVE
        and action.metadata.get("body_instruction_execution") is True
    ]
    assert len(body_moves) == 1
    assert body_moves[0].metadata["explicit_body_instruction"] == instruction.as_context()

    ordered = ActionScheduler._synchronized_action_order(
        ActionPlanGroup(action_plans=actions, group_id="output-1")
    )
    move_index = next(
        index for index, action in enumerate(ordered)
        if action.action_type is ActionType.MOVE
    )
    speak_index = next(
        index for index, action in enumerate(ordered)
        if action.action_type is ActionType.SPEAK
    )
    assert move_index < speak_index


def test_action_planner_does_not_emit_move_without_preflight_ready() -> None:
    instruction = BodyInstruction("head", "right", magnitude=0.8)
    activity = _activity(instruction)
    event_payload = dict(activity.context["event_payload"])
    event_payload["body_instruction_execution_ready"] = False
    activity = Activity(
        activity_type=activity.activity_type,
        goal=activity.goal,
        context={"event_payload": event_payload},
    )
    planner = AvatarPerformanceActionPlanner(cast(Any, MagicMock()))

    actions = planner._reaction_action_plans(
        activity,
        CharacterResponse(speech="うん。", expression="neutral"),
        fallback_speech="うん。",
        output_unit_id="output-2",
        base_metadata={},
        skip_topic_memory=False,
    )

    assert not any(
        action.action_type is ActionType.MOVE
        and action.metadata.get("body_instruction_execution") is True
        for action in actions
    )


class _AppliedExecutor:
    def __init__(self) -> None:
        self.instructions: list[BodyInstruction] = []

    async def execute(self, instruction: BodyInstruction) -> BodyConstraintExecutionResult:
        self.instructions.append(instruction)
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.APPLIED,
            constraint_id="output-constraint",
            reason="body_constraint_applied",
            target_axes=(BodyPoseAxis.RIGHT_ARM_RAISE.value,),
        )


class _RejectedExecutor:
    async def execute(self, instruction: BodyInstruction) -> BodyConstraintExecutionResult:
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.REJECTED,
            constraint_id=None,
            reason="body_constraint_rejected",
        )


def _move(instruction: BodyInstruction) -> ActionPlan:
    return ActionPlan(
        action_type=ActionType.MOVE,
        text="explicit_body_instruction",
        required_resources={ActionResource.BODY},
        source_activity_id="activity-1",
        output_unit_id="output-1",
        metadata={
            "body_instruction_execution": True,
            "explicit_body_instruction": instruction.as_context(),
        },
    )


@pytest.mark.asyncio
async def test_body_aware_execute_action_applies_explicit_move_at_output_time() -> None:
    instruction = BodyInstruction("arm", "up", side="right", magnitude=0.9)
    executor = _AppliedExecutor()
    usecase = BodyAwareExecuteActionUsecase(
        body_instruction_executor=cast(Any, executor)
    )

    result = await usecase.execute(_move(instruction))

    assert result is None
    assert executor.instructions == [instruction]


@pytest.mark.asyncio
async def test_body_aware_execute_action_fails_closed_when_move_is_rejected() -> None:
    usecase = BodyAwareExecuteActionUsecase(
        body_instruction_executor=cast(Any, _RejectedExecutor())
    )

    with pytest.raises(RuntimeError, match="body_constraint_not_applied"):
        await usecase.execute(
            _move(BodyInstruction("head", "right", magnitude=0.8))
        )
