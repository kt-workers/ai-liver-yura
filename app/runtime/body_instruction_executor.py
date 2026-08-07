from __future__ import annotations

from collections.abc import Callable

from app.domain.body_instruction import (
    BodyConstraintExecutionResult,
    BodyConstraintExecutionStatus,
    BodyInstruction,
)
from app.domain.body_pose_dynamics import BodyExternalConstraint
from app.ports.body_subsystem import BodySubsystemPort, get_bound_body_subsystem
from app.runtime.body_instruction_constraint_resolver import (
    BodyInstructionConstraintResolver,
)


class BodyInstructionExecutor:
    """意味解決済みBody指示を現在のBody Subsystemへ一度だけ適用する。"""

    def __init__(
        self,
        *,
        body_provider: Callable[[], BodySubsystemPort | None] = get_bound_body_subsystem,
        resolver: BodyInstructionConstraintResolver | None = None,
    ) -> None:
        self._body_provider = body_provider
        self._resolver = resolver or BodyInstructionConstraintResolver()

    async def execute(self, instruction: BodyInstruction) -> BodyConstraintExecutionResult:
        resolution = self._resolver.resolve(instruction)
        constraint = resolution.constraint
        if constraint is None:
            return BodyConstraintExecutionResult(
                status=BodyConstraintExecutionStatus.UNSUPPORTED,
                constraint_id=None,
                reason=resolution.reason,
            )

        body = self._body_provider()
        if body is None:
            return self._unsupported(constraint, "body_subsystem_unavailable")
        apply_constraint = getattr(body, "apply_external_constraint", None)
        if not callable(apply_constraint):
            return self._unsupported(constraint, "body_constraint_port_unavailable")
        try:
            result = await apply_constraint(constraint)
        except Exception as error:
            return BodyConstraintExecutionResult(
                status=BodyConstraintExecutionStatus.REJECTED,
                constraint_id=constraint.constraint_id,
                reason=f"body_constraint_apply_failed:{type(error).__name__}",
                target_axes=self._target_axes(constraint),
            )
        if isinstance(result, BodyConstraintExecutionResult):
            return result
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.APPLIED,
            constraint_id=constraint.constraint_id,
            reason="body_constraint_applied",
            target_axes=self._target_axes(constraint),
        )

    @classmethod
    def _unsupported(
        cls,
        constraint: BodyExternalConstraint,
        reason: str,
    ) -> BodyConstraintExecutionResult:
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.UNSUPPORTED,
            constraint_id=constraint.constraint_id,
            reason=reason,
            target_axes=cls._target_axes(constraint),
        )

    @staticmethod
    def _target_axes(constraint: BodyExternalConstraint) -> tuple[str, ...]:
        return tuple(target.axis.value for target in constraint.targets)


__all__ = ["BodyInstructionExecutor"]
