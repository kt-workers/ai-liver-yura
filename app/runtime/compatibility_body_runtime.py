from __future__ import annotations

from app.domain.body_instruction import (
    BodyConstraintExecutionResult,
    BodyConstraintExecutionStatus,
)
from app.domain.body_pose_dynamics import BodyExternalConstraint
from app.runtime.body_runtime import BodyRuntime


class CompatibilityBodyRuntime(BodyRuntime):
    """旧AvatarPerformance経路を維持しつつ、外部Pose制約は未対応と明示する。"""

    async def apply_external_constraint(
        self,
        constraint: BodyExternalConstraint,
    ) -> BodyConstraintExecutionResult:
        if not isinstance(constraint, BodyExternalConstraint):
            raise TypeError("constraint must be BodyExternalConstraint")
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.UNSUPPORTED,
            constraint_id=constraint.constraint_id,
            reason="body_constraint_not_supported_by_compatibility_runtime",
            target_axes=tuple(target.axis.value for target in constraint.targets),
        )


__all__ = ["CompatibilityBodyRuntime"]
