from __future__ import annotations

from typing import Any, cast

import pytest

from app.domain.activities import Activity, ActivityType
from app.domain.body_instruction import (
    BodyConstraintExecutionResult,
    BodyConstraintExecutionStatus,
    BodyInstruction,
)
from app.domain.body_pose_dynamics import BodyExternalConstraint
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)
from app.runtime.body_aware_response_validation import BodyAwareResponseValidator
from app.runtime.body_instruction_executor import BodyInstructionExecutor


class _InvalidResultBody:
    async def apply_external_constraint(self, constraint: BodyExternalConstraint) -> object:
        return object()


class _MismatchedAppliedBody:
    async def apply_external_constraint(
        self,
        constraint: BodyExternalConstraint,
    ) -> BodyConstraintExecutionResult:
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.APPLIED,
            constraint_id="different-constraint",
            reason="body_constraint_applied",
            target_axes=tuple(target.axis.value for target in constraint.targets),
        )


class _AcceptedBody:
    async def apply_external_constraint(
        self,
        constraint: BodyExternalConstraint,
    ) -> BodyConstraintExecutionResult:
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.ACCEPTED,
            constraint_id=constraint.constraint_id,
            reason="body_constraint_accepted",
            target_axes=tuple(target.axis.value for target in constraint.targets),
        )


@pytest.mark.asyncio
async def test_executor_rejects_untyped_body_result_instead_of_assuming_applied() -> None:
    executor = BodyInstructionExecutor(
        body_provider=lambda: cast(Any, _InvalidResultBody())
    )

    result = await executor.execute(BodyInstruction("head", "right", magnitude=0.8))

    assert result.status is BodyConstraintExecutionStatus.REJECTED
    assert result.applied is False
    assert result.reason == "body_constraint_result_invalid"


@pytest.mark.asyncio
async def test_executor_rejects_applied_result_for_different_constraint() -> None:
    executor = BodyInstructionExecutor(
        body_provider=lambda: cast(Any, _MismatchedAppliedBody())
    )

    result = await executor.execute(
        BodyInstruction("arm", "up", side="right", magnitude=0.9)
    )

    assert result.status is BodyConstraintExecutionStatus.REJECTED
    assert result.applied is False
    assert result.reason == "body_constraint_result_mismatch"


@pytest.mark.asyncio
async def test_accepted_body_result_is_not_execution_success() -> None:
    executor = BodyInstructionExecutor(body_provider=lambda: cast(Any, _AcceptedBody()))

    result = await executor.execute(BodyInstruction("head", "right", magnitude=0.8))

    assert result.status is BodyConstraintExecutionStatus.ACCEPTED
    assert result.accepted is True
    assert result.applied is False


def _act_context_without_execution_result() -> ResponseContext:
    intention = InteractionIntention(
        intention=InteractionIntentionType.ACT,
        confidence=0.98,
        source="test",
        reason="explicit_body_instruction",
        activity_type=ActivityType.BODY_EXPRESSION_LOOP.value,
        observation_only=True,
    )
    return ResponseContext(
        user_input="右手挙げて",
        activity_type="conversation",
        operation="start",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(
            ResponseClaim.ACTIVITY_COMPLETED,
            ResponseClaim.ACTIVITY_SUCCEEDED,
            ResponseClaim.EXTERNAL_RESULT_OBTAINED,
        ),
        activity_goal="身体方向を一時制約として適用する",
        memory={"interaction_intention": intention.as_context()},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "speech",
    (
        "うん、右手を挙げてる感じでいるよ。",
        "了解、右を見てる感じでいるよ。",
        "今はそっちを向いているよ。",
        "右腕を動かしてるよ。",
    ),
)
async def test_progressive_or_hedged_body_claim_is_rejected_without_applied_result(
    speech: str,
) -> None:
    validator = BodyAwareResponseValidator()
    source = Activity(ActivityType.BEHAVIOR_PLANNING, "respond")
    response = CharacterResponse(
        speech=speech,
        claims=(ResponseClaim.CONVERSATION_ONLY,),
    )

    result = await validator.validate(
        source,
        _act_context_without_execution_result(),
        response,
    )

    assert result.accepted is False
    assert "activity_succeeded" in result.reason
