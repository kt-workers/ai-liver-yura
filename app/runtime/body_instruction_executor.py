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
    """意味解決済みBody指示の事前確認と実適用を分離する。"""

    def __init__(
        self,
        *,
        body_provider: Callable[[], BodySubsystemPort | None] = get_bound_body_subsystem,
        resolver: BodyInstructionConstraintResolver | None = None,
    ) -> None:
        self._body_provider = body_provider
        self._resolver = resolver or BodyInstructionConstraintResolver()

    def preflight(self, instruction: BodyInstruction) -> BodyConstraintExecutionResult:
        """Character生成前に、実行可能性だけを確認する。

        ConstraintはまだControllerへ適用しない。ACCEPTEDは出力段階でMOVEを
        実行できる見込みがあることだけを表し、身体動作成功の根拠にはしない。
        """

        resolution = self._resolver.resolve(instruction)
        constraint = resolution.constraint
        if constraint is None:
            return BodyConstraintExecutionResult(
                status=BodyConstraintExecutionStatus.UNSUPPORTED,
                constraint_id=None,
                reason=resolution.reason,
            )
        if self._body_provider() is None:
            return self._unsupported(constraint, "body_subsystem_unavailable")
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.ACCEPTED,
            constraint_id=None,
            reason="body_constraint_ready_for_output",
            target_axes=self._target_axes(constraint),
        )

    async def execute(self, instruction: BodyInstruction) -> BodyConstraintExecutionResult:
        """出力段階で正規化Body制約を現在のBody Subsystemへ一度だけ適用する。"""

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
        try:
            result = await body.apply_external_constraint(constraint)
        except Exception as error:
            return self._rejected(
                constraint,
                f"body_constraint_apply_failed:{type(error).__name__}",
            )
        if not isinstance(result, BodyConstraintExecutionResult):
            return self._rejected(constraint, "body_constraint_result_invalid")
        if (
            result.status
            in {
                BodyConstraintExecutionStatus.ACCEPTED,
                BodyConstraintExecutionStatus.APPLIED,
            }
            and result.constraint_id != constraint.constraint_id
        ):
            return self._rejected(constraint, "body_constraint_result_mismatch")
        return result

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

    @classmethod
    def _rejected(
        cls,
        constraint: BodyExternalConstraint,
        reason: str,
    ) -> BodyConstraintExecutionResult:
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.REJECTED,
            constraint_id=constraint.constraint_id,
            reason=reason,
            target_axes=cls._target_axes(constraint),
        )

    @staticmethod
    def _target_axes(constraint: BodyExternalConstraint) -> tuple[str, ...]:
        return tuple(target.axis.value for target in constraint.targets)


__all__ = ["BodyInstructionExecutor"]
