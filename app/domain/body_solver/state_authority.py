from __future__ import annotations

from datetime import datetime
from threading import Lock

from app.domain.body import BodyPose, BodyState, BodyVelocity, CanonicalBodyModel
from app.domain.contracts.common import require_aware, require_revision, utc_instant

from .contracts import BodyFrameChannelValue, BodyPoseFrame, BodySolverFailureCode


class BodyStateCommitError(ValueError):
    def __init__(self, code: BodySolverFailureCode) -> None:
        super().__init__(code.value)
        self.code = code


class BodyStateAuthority:
    """#339だけがCanonical BodyState revisionを進める短時間commit境界。"""

    def __init__(
        self,
        model: CanonicalBodyModel,
        initial_state: BodyState,
        *,
        history_limit: int = 120,
    ) -> None:
        if not isinstance(model, CanonicalBodyModel):
            raise ValueError("model が不正です")
        if not isinstance(initial_state, BodyState):
            raise ValueError("initial_state が不正です")
        initial_state.validate_for(model)
        if type(history_limit) is not int or history_limit < 0:
            raise ValueError("history_limit は0以上の整数でなければなりません")
        self._model = model
        self._current = initial_state
        self._history_limit = history_limit
        self._lock = Lock()

    @property
    def current(self) -> BodyState:
        with self._lock:
            return self._current

    def commit_validated_frame(
        self,
        *,
        expected_revision: int,
        frame_id: str,
        observed_at: datetime,
        pose: BodyPose,
        velocity: BodyVelocity,
        active_plan_id: str | None,
        active_trajectory_id: str | None,
        channel_values: tuple[BodyFrameChannelValue, ...],
        applied_overlay_refs: tuple[str, ...],
        degraded_overlay_refs: tuple[str, ...],
        trace_id: str,
    ) -> BodyPoseFrame:
        """solverのhard validationを通過したframeだけをrevision付きでcommitする。"""

        require_revision(expected_revision, "expected_revision")
        require_aware(observed_at, "observed_at")
        if (active_plan_id is None) != (active_trajectory_id is None):
            raise ValueError("active planとtrajectoryは対で指定しなければなりません")
        if not isinstance(pose, BodyPose) or not isinstance(velocity, BodyVelocity):
            raise ValueError("pose / velocity が不正です")
        pose.validate_for(self._model)
        velocity.validate_for(self._model)

        with self._lock:
            current = self._current
            if expected_revision != current.revision:
                raise BodyStateCommitError(BodySolverFailureCode.STALE_HARD_DEPENDENCY)
            if utc_instant(observed_at) < utc_instant(current.observed_at):
                raise BodyStateCommitError(BodySolverFailureCode.STALE_HARD_DEPENDENCY)

            history = current.history + ((current.observed_at, current.pose),)
            if self._history_limit == 0:
                history = ()
            elif len(history) > self._history_limit:
                history = history[-self._history_limit :]

            next_state = BodyState(
                body_model_id=self._model.body_model_id,
                revision=current.revision + 1,
                observed_at=observed_at,
                pose=pose,
                velocity=velocity,
                history=history,
            )
            next_state.validate_for(self._model)
            frame = BodyPoseFrame(
                frame_id=frame_id,
                body_model_id=self._model.body_model_id,
                body_state_revision=next_state.revision,
                observed_at=observed_at,
                pose=pose,
                velocity=velocity,
                active_plan_id=active_plan_id,
                active_trajectory_id=active_trajectory_id,
                channel_values=channel_values,
                applied_overlay_refs=applied_overlay_refs,
                degraded_overlay_refs=degraded_overlay_refs,
                trace_id=trace_id,
            )
            self._current = next_state
            return frame
