from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Protocol

from app.domain.body import CanonicalBodyModel
from app.domain.body_realtime import RealtimeChannel
from app.domain.body_solver import BodyPoseFrame
from app.domain.contracts.common import require_aware

from .contracts import (
    AvatarModelBinding,
    AvatarProjectionCommand,
    AvatarProjectionReport,
    AvatarProjectionStatus,
    AvatarRendererResult,
    AvatarRendererStatus,
)
from .projection import project_body_pose_frame, validate_avatar_model_binding


class AvatarRendererPort(Protocol):
    def present(
        self,
        command: AvatarProjectionCommand,
        *,
        started_at: datetime,
    ) -> AvatarRendererResult: ...


@dataclass(frozen=True, slots=True)
class _QueuedFrame:
    frame: BodyPoseFrame
    binding_revision: int
    binding_generation: int


class AvatarPresentationRuntime:
    """Core producerをrenderer I/Oから分離するlatest-frame consumer runtime。"""

    def __init__(
        self,
        model: CanonicalBodyModel,
        binding: AvatarModelBinding,
        renderer: AvatarRendererPort,
    ) -> None:
        if not isinstance(model, CanonicalBodyModel):
            raise ValueError("modelが不正です")
        validate_avatar_model_binding(binding, model)
        if not hasattr(renderer, "present"):
            raise ValueError("rendererが不正です")
        self._model = model
        self._binding = binding
        self._renderer = renderer
        self._latest_frame: BodyPoseFrame | None = None
        self._queued: _QueuedFrame | None = None
        self._coalesced_since_present = 0
        self._last_presented_revision: dict[int, int] = {}
        self._last_presented_at: dict[int, datetime] = {}
        self._lock = Lock()

    @property
    def pending_frame_count(self) -> int:
        with self._lock:
            return int(self._queued is not None)

    @property
    def binding(self) -> AvatarModelBinding:
        with self._lock:
            return self._binding

    @property
    def latest_frame(self) -> BodyPoseFrame | None:
        with self._lock:
            return self._latest_frame

    def submit_frame(self, frame: BodyPoseFrame) -> None:
        if not isinstance(frame, BodyPoseFrame):
            raise ValueError("frameが不正です")
        if frame.body_model_id != self._model.body_model_id:
            raise ValueError("frameのCanonical Body Modelが一致しません")
        frame.pose.validate_for(self._model)
        with self._lock:
            if self._queued is not None:
                self._coalesced_since_present += 1
            self._latest_frame = frame
            self._queued = _QueuedFrame(
                frame,
                self._binding.binding_revision,
                self._binding.binding_generation,
            )

    def reload_binding(self, binding: AvatarModelBinding) -> None:
        validate_avatar_model_binding(binding, self._model)
        with self._lock:
            current = self._binding
            if binding.binding_generation <= current.binding_generation:
                raise ValueError("binding_generationはreloadごとに増加する必要があります")
            if self._queued is not None:
                self._coalesced_since_present += 1
            self._binding = binding
            latest = self._latest_frame
            self._queued = (
                None
                if latest is None
                else _QueuedFrame(
                    latest,
                    binding.binding_revision,
                    binding.binding_generation,
                )
            )

    def present_latest(self, *, started_at: datetime) -> AvatarProjectionReport | None:
        require_aware(started_at, "started_at")
        with self._lock:
            queued = self._queued
            if queued is None:
                return None
            self._queued = None
            coalesced = self._coalesced_since_present
            self._coalesced_since_present = 0
            binding = self._binding
            last_revision = self._last_presented_revision.get(queued.binding_generation)
            last_observed_at = self._last_presented_at.get(queued.binding_generation)

        if (
            queued.binding_generation != binding.binding_generation
            or queued.binding_revision != binding.binding_revision
        ):
            return self._stale_report(
                queued.frame,
                binding,
                started_at,
                coalesced + 1,
                "binding_generation_stale",
            )
        if last_revision is not None and queued.frame.body_state_revision <= last_revision:
            return self._stale_report(
                queued.frame,
                binding,
                started_at,
                coalesced + 1,
                "body_revision_stale",
            )
        if last_observed_at is not None and queued.frame.observed_at < last_observed_at:
            return self._stale_report(
                queued.frame,
                binding,
                started_at,
                coalesced + 1,
                "frame_timestamp_stale",
            )

        command = project_body_pose_frame(queued.frame, binding, self._model)
        renderer_result = self._renderer.present(command, started_at=started_at)
        if not isinstance(renderer_result, AvatarRendererResult):
            raise ValueError("renderer resultが不正です")

        with self._lock:
            current_binding = self._binding
            generation_changed = (
                current_binding.binding_generation != command.binding_generation
                or current_binding.binding_revision != command.binding_revision
            )
            if generation_changed:
                self._queue_latest_for_current_binding_locked()
            elif renderer_result.status is AvatarRendererStatus.APPLIED:
                self._last_presented_revision[command.binding_generation] = (
                    command.body_state_revision
                )
                self._last_presented_at[command.binding_generation] = command.observed_at
            else:
                self._queue_latest_for_current_binding_locked()

        if generation_changed:
            diagnostics = tuple(
                sorted(set(renderer_result.sanitized_diagnostics) | {"binding_changed_in_flight"})
            )
            return self._report(
                command,
                AvatarProjectionStatus.DROPPED_STALE,
                started_at,
                renderer_result.completed_at,
                coalesced + 1,
                (),
                (),
                command.degraded_items,
                diagnostics,
            )
        if renderer_result.status is AvatarRendererStatus.UNAVAILABLE:
            return self._report(
                command,
                AvatarProjectionStatus.OUTPUT_UNAVAILABLE,
                started_at,
                renderer_result.completed_at,
                coalesced,
                (),
                (),
                command.degraded_items,
                renderer_result.sanitized_diagnostics,
            )
        if renderer_result.status is AvatarRendererStatus.FAILED:
            return self._report(
                command,
                AvatarProjectionStatus.FAILED,
                started_at,
                renderer_result.completed_at,
                coalesced,
                (),
                (),
                command.degraded_items,
                renderer_result.sanitized_diagnostics,
            )
        status = (
            AvatarProjectionStatus.PARTIALLY_APPLIED
            if command.degraded_items
            else AvatarProjectionStatus.APPLIED
        )
        return self._report(
            command,
            status,
            started_at,
            renderer_result.completed_at,
            coalesced,
            tuple(value.canonical_joint_id for value in command.joint_projections),
            tuple(value.canonical_channel for value in command.channel_projections),
            command.degraded_items,
            renderer_result.sanitized_diagnostics,
        )

    def _queue_latest_for_current_binding_locked(self) -> None:
        if self._queued is not None or self._latest_frame is None:
            return
        self._queued = _QueuedFrame(
            self._latest_frame,
            self._binding.binding_revision,
            self._binding.binding_generation,
        )

    def _stale_report(
        self,
        frame: BodyPoseFrame,
        binding: AvatarModelBinding,
        at: datetime,
        dropped: int,
        diagnostic: str,
    ) -> AvatarProjectionReport:
        return AvatarProjectionReport(
            frame.frame_id,
            binding.binding_id,
            binding.binding_revision,
            binding.binding_generation,
            binding.model_identity,
            AvatarProjectionStatus.DROPPED_STALE,
            (),
            (),
            (),
            at,
            at,
            dropped,
            (diagnostic,),
        )

    @staticmethod
    def _report(
        command: AvatarProjectionCommand,
        status: AvatarProjectionStatus,
        started_at: datetime,
        completed_at: datetime,
        dropped: int,
        applied_joint_ids: tuple[str, ...],
        applied_channels: tuple[RealtimeChannel, ...],
        degraded_items: tuple[str, ...],
        diagnostics: tuple[str, ...],
    ) -> AvatarProjectionReport:
        return AvatarProjectionReport(
            command.frame_id,
            command.binding_id,
            command.binding_revision,
            command.binding_generation,
            command.model_identity,
            status,
            applied_joint_ids,
            applied_channels,
            degraded_items,
            started_at,
            completed_at,
            dropped,
            diagnostics,
        )
