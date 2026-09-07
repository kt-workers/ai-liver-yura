from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from app.domain.contracts.common import require_revision


def _positive(value: int | float, name: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(f"{name}は正のfinite numberでなければなりません")
    return float(value)


@dataclass(frozen=True, slots=True)
class BodySolverPolicy:
    """#339 numerical solver/controlのversioned Authority。"""

    policy_revision: int
    target_control_rate_hz: float
    numeric_epsilon: float
    max_ik_iterations: int
    position_residual_tolerance_ratio: float
    orientation_residual_tolerance_radians: float
    completion_position_tolerance_ratio: float
    completion_orientation_tolerance_radians: float
    minimum_support_margin_ratio: float
    max_per_iteration_dof_step_radians: float

    def __post_init__(self) -> None:
        require_revision(self.policy_revision, "policy_revision")
        for name in (
            "target_control_rate_hz",
            "numeric_epsilon",
            "position_residual_tolerance_ratio",
            "orientation_residual_tolerance_radians",
            "completion_position_tolerance_ratio",
            "completion_orientation_tolerance_radians",
            "minimum_support_margin_ratio",
            "max_per_iteration_dof_step_radians",
        ):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        if type(self.max_ik_iterations) is not int or self.max_ik_iterations < 1:
            raise ValueError("max_ik_iterationsは1以上のintでなければなりません")

    @property
    def target_control_interval_seconds(self) -> float:
        return 1.0 / self.target_control_rate_hz

    def position_tolerance_m(self, reference_height: float, *, completion: bool = False) -> float:
        height = _positive(reference_height, "reference_height")
        ratio = (
            self.completion_position_tolerance_ratio
            if completion
            else self.position_residual_tolerance_ratio
        )
        return height * ratio


def v2_baseline_body_solver_policy() -> BodySolverPolicy:
    """D10 canonical initial V2 baselineを明示的に選択するComposition helper。"""

    return BodySolverPolicy(
        policy_revision=1,
        target_control_rate_hz=60.0,
        numeric_epsilon=1e-9,
        max_ik_iterations=64,
        position_residual_tolerance_ratio=0.01,
        orientation_residual_tolerance_radians=0.017453292519943295,
        completion_position_tolerance_ratio=0.015,
        completion_orientation_tolerance_radians=0.03490658503988659,
        minimum_support_margin_ratio=0.01,
        max_per_iteration_dof_step_radians=0.08726646259971647,
    )
