from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from time import monotonic

from app.domain.body_activity_context import BodyActivityContext
from app.domain.body_expression_request import BodyExpressionRequest
from app.domain.body_instruction import (
    BodyConstraintExecutionResult,
    BodyConstraintExecutionStatus,
)
from app.domain.body_pose_dynamics import BodyExternalConstraint
from app.domain.body_pose_frame import BodyPoseFrame
from app.domain.body_runtime import BodyRuntimeSnapshot
from app.domain.body_speech import SpeechPresentationRequest
from app.domain.emotions.emotion_state import EmotionState
from app.ports.body_pose_output import BodyPoseFrameOutputPort
from app.runtime.body_expression_input_builder import BodyExpressionInputBuilder
from app.runtime.body_expression_request_store import (
    TimedBodyExpressionRequestStore,
)
from app.runtime.state_driven_body_controller import StateDrivenBodyController
from app.utils.trace import TraceLogger


class StateDrivenBodyPoseRuntime:
    """Emotion・Activity・Expression入力をControllerへ渡しFrameを公開する薄いRuntime。"""

    def __init__(
        self,
        *,
        controller: StateDrivenBodyController,
        output: BodyPoseFrameOutputPort,
        emotion_provider: Callable[[], EmotionState],
        initial_context: BodyActivityContext,
        input_builder: BodyExpressionInputBuilder | None = None,
        expression_store: TimedBodyExpressionRequestStore | None = None,
    ) -> None:
        if not isinstance(controller, StateDrivenBodyController):
            raise TypeError("controller must be StateDrivenBodyController")
        if not callable(emotion_provider):
            raise TypeError("emotion_provider must be callable")
        if not isinstance(initial_context, BodyActivityContext):
            raise TypeError("initial_context must be BodyActivityContext")
        self._controller = controller
        self._output = output
        self._emotion_provider = emotion_provider
        self._context = initial_context
        self._input_builder = input_builder or BodyExpressionInputBuilder()
        self._expression_store = (
            expression_store or TimedBodyExpressionRequestStore()
        )
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._tick_count = 0
        self._last_frame_id: str | None = None
        self._last_error: str | None = None
        self._trace = TraceLogger()
        self._constraint_trace_id: str | None = None
        self._constraint_trace_axes: tuple[str, ...] = ()
        self._constraint_trace_frames_remaining = 0

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(
            self._run(),
            name="state-driven-body-pose-runtime",
        )

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._output.close()
        self._controller.clear_speech()
        self._controller.clear_external_constraint()
        self._expression_store.clear()

    async def update_activity_context(self, context: BodyActivityContext) -> None:
        if not isinstance(context, BodyActivityContext):
            raise TypeError("context must be BodyActivityContext")
        self._context = context

    async def request_expression(self, request: BodyExpressionRequest) -> None:
        self._expression_store.set(request)

    async def apply_external_constraint(
        self,
        constraint: BodyExternalConstraint,
    ) -> BodyConstraintExecutionResult:
        if not isinstance(constraint, BodyExternalConstraint):
            raise TypeError("constraint must be BodyExternalConstraint")
        self._controller.apply_external_constraint(constraint)
        target_axes = tuple(target.axis.value for target in constraint.targets)
        self._constraint_trace_id = constraint.constraint_id
        self._constraint_trace_axes = target_axes
        self._constraint_trace_frames_remaining = max(
            1,
            int(round(self._controller.tick_hz * 2.5)),
        )
        self._trace.info(
            "body_constraint_runtime_applied",
            constraint_id=constraint.constraint_id,
            active_constraint_id=self._controller.active_constraint_id,
            duration_ms=constraint.duration_ms,
            targets=[
                {
                    "axis": target.axis.value,
                    "value": target.value,
                    "weight": target.weight,
                }
                for target in constraint.targets
            ],
        )
        return BodyConstraintExecutionResult(
            status=BodyConstraintExecutionStatus.APPLIED,
            constraint_id=constraint.constraint_id,
            reason="body_constraint_applied",
            target_axes=target_axes,
        )

    async def present_speech(self, request: SpeechPresentationRequest) -> None:
        current = self._controller.expression_input
        energy = max(
            current.activity_context.movement_energy,
            current.affect_baseline.expressiveness,
        )
        self._controller.present_speech(request, energy=energy)

    async def snapshot(self) -> BodyRuntimeSnapshot:
        return BodyRuntimeSnapshot(
            running=self._running,
            tick_count=self._tick_count,
            active_activity_id=self._context.source_activity_id,
            pending_expression_count=self._expression_store.pending_count,
            active_speech_id=self._controller.active_speech_id,
            last_performance_id=self._last_frame_id,
            last_error=self._last_error,
        )

    async def tick_once(self) -> BodyPoseFrame:
        """確定済みEmotionと現在Contextから1Frameだけ生成・公開する。"""

        emotion = self._emotion_provider()
        if not isinstance(emotion, EmotionState):
            raise TypeError("emotion_provider must return EmotionState")
        expression_input = self._input_builder.build(
            emotion=emotion,
            context=self._context,
            expression_request=self._expression_store.current(),
        )
        self._controller.update_expression_input(expression_input)
        active_constraint_before_tick = self._controller.active_constraint_id
        frame = self._controller.tick()
        self._trace_constraint_frame(
            frame,
            active_constraint_before_tick=active_constraint_before_tick,
        )
        await self._output.publish_body_pose_frame(frame)
        self._tick_count += 1
        self._last_frame_id = f"body-frame-{frame.sequence}"
        self._last_error = None
        return frame

    def _trace_constraint_frame(
        self,
        frame: BodyPoseFrame,
        *,
        active_constraint_before_tick: str | None,
    ) -> None:
        constraint_id = self._constraint_trace_id
        if constraint_id is None or self._constraint_trace_frames_remaining <= 0:
            return
        pose_axes = {
            axis: getattr(frame.pose, axis)
            for axis in self._constraint_trace_axes
            if hasattr(frame.pose, axis)
        }
        self._trace.debug(
            "body_constraint_pose_frame_generated",
            constraint_id=constraint_id,
            frame_sequence=frame.sequence,
            active_constraint_id_before_tick=active_constraint_before_tick,
            active_constraint_id_after_tick=self._controller.active_constraint_id,
            pose_axes=pose_axes,
        )
        if (
            active_constraint_before_tick == constraint_id
            and self._controller.active_constraint_id is None
        ):
            self._trace.info(
                "body_constraint_runtime_completed",
                constraint_id=constraint_id,
                frame_sequence=frame.sequence,
                pose_axes=pose_axes,
            )
        self._constraint_trace_frames_remaining -= 1
        if self._constraint_trace_frames_remaining <= 0:
            self._constraint_trace_id = None
            self._constraint_trace_axes = ()

    async def _run(self) -> None:
        interval = 1.0 / self._controller.tick_hz
        while self._running:
            started = monotonic()
            try:
                await self.tick_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._last_error = f"{type(error).__name__}: {error}"[:240]
            elapsed = monotonic() - started
            await asyncio.sleep(max(0.0, interval - elapsed))
