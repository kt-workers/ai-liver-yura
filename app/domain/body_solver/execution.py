from __future__ import annotations

from datetime import datetime
from enum import Enum
from threading import Lock

from app.domain.contracts.common import require_aware, require_identifier, utc_instant

from .contracts import (
    BodyMotionExecutionReport,
    BodyMotionExecutionStatus,
    BodyMotionResidual,
)


class BodyExecutionTransitionFailureCode(str, Enum):
    INVALID_TRANSITION = "invalid_transition"
    TIME_ROLLBACK = "time_rollback"


class BodyExecutionTransitionError(ValueError):
    def __init__(self, code: BodyExecutionTransitionFailureCode) -> None:
        super().__init__(code.value)
        self.code = code


def _require_forward_time(candidate: datetime, anchor: datetime) -> None:
    require_aware(candidate, "observed_at")
    if utc_instant(candidate) < utc_instant(anchor):
        raise BodyExecutionTransitionError(
            BodyExecutionTransitionFailureCode.TIME_ROLLBACK
        )


class BodyMotionExecutionTracker:
    """physical evidenceだけでPLANNEDからCOMPLETEDまでを昇格させる。"""

    def __init__(self, plan_id: str, trajectory_id: str) -> None:
        require_identifier(plan_id, "plan_id")
        require_identifier(trajectory_id, "trajectory_id")
        self._current = BodyMotionExecutionReport(
            plan_id=plan_id,
            trajectory_id=trajectory_id,
            status=BodyMotionExecutionStatus.PLANNED,
        )
        self._lock = Lock()

    @property
    def current(self) -> BodyMotionExecutionReport:
        with self._lock:
            return self._current

    def start(self, observed_at: datetime) -> BodyMotionExecutionReport:
        require_aware(observed_at, "observed_at")
        with self._lock:
            if self._current.status is not BodyMotionExecutionStatus.PLANNED:
                raise BodyExecutionTransitionError(
                    BodyExecutionTransitionFailureCode.INVALID_TRANSITION
                )
            self._current = BodyMotionExecutionReport(
                plan_id=self._current.plan_id,
                trajectory_id=self._current.trajectory_id,
                status=BodyMotionExecutionStatus.STARTED,
                started_at=observed_at,
            )
            return self._current

    def observe(
        self,
        observed_at: datetime,
        *,
        achieved_target_refs: tuple[str, ...] = (),
        residuals: tuple[BodyMotionResidual, ...] = (),
    ) -> BodyMotionExecutionReport:
        with self._lock:
            current = self._current
            if current.status not in {
                BodyMotionExecutionStatus.STARTED,
                BodyMotionExecutionStatus.OBSERVABLE,
            }:
                raise BodyExecutionTransitionError(
                    BodyExecutionTransitionFailureCode.INVALID_TRANSITION
                )
            assert current.started_at is not None
            anchor = current.observable_at or current.started_at
            _require_forward_time(observed_at, anchor)
            self._current = BodyMotionExecutionReport(
                plan_id=current.plan_id,
                trajectory_id=current.trajectory_id,
                status=BodyMotionExecutionStatus.OBSERVABLE,
                started_at=current.started_at,
                observable_at=current.observable_at or observed_at,
                achieved_target_refs=achieved_target_refs,
                residuals=residuals,
            )
            return self._current

    def complete(
        self,
        observed_at: datetime,
        *,
        achieved_target_refs: tuple[str, ...] = (),
        residuals: tuple[BodyMotionResidual, ...] = (),
    ) -> BodyMotionExecutionReport:
        with self._lock:
            current = self._current
            if current.status not in {
                BodyMotionExecutionStatus.STARTED,
                BodyMotionExecutionStatus.OBSERVABLE,
            }:
                raise BodyExecutionTransitionError(
                    BodyExecutionTransitionFailureCode.INVALID_TRANSITION
                )
            assert current.started_at is not None
            anchor = current.observable_at or current.started_at
            _require_forward_time(observed_at, anchor)
            self._current = BodyMotionExecutionReport(
                plan_id=current.plan_id,
                trajectory_id=current.trajectory_id,
                status=BodyMotionExecutionStatus.COMPLETED,
                started_at=current.started_at,
                observable_at=current.observable_at,
                completed_at=observed_at,
                achieved_target_refs=achieved_target_refs,
                residuals=residuals,
            )
            return self._current
