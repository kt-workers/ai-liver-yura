from __future__ import annotations

from collections import deque
from io import BytesIO
from typing import Any
from wave import Error as WaveError
from wave import open as open_wave

from app.domain.actions import ActionPlan, ActionType
from app.domain.activity_turn_result import ActionExecutionResult
from app.domain.avatar_performance import AvatarPerformancePlan
from app.domain.body import (
    BodyActivityContext,
    BodyExpressionRequest,
    SpeechEmphasis,
    SpeechPresentationRequest,
)
from app.ports.avatar_output import AvatarOutputPort, get_bound_avatar_output
from app.ports.body_subsystem import BodySubsystemPort, get_bound_body_subsystem
from app.usecases.delivery_aware_execute_action_usecase import (
    ExecuteActionUsecase as DeliveryAwareExecuteActionUsecase,
)
from app.utils.trace import TraceLogger


class ExecuteActionUsecase(DeliveryAwareExecuteActionUsecase):
    """既存Action実行へBody Subsystemと交換可能なAvatar出力を合成する。"""

    _MAX_TRACKED_PERFORMANCES = 256
    _MAX_TRACKED_BODY_REQUESTS = 256

    def __init__(
        self,
        *args: Any,
        avatar_output: AvatarOutputPort | None = None,
        body_subsystem: BodySubsystemPort | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._avatar_output = (
            avatar_output if avatar_output is not None else get_bound_avatar_output()
        )
        self._body_subsystem = (
            body_subsystem
            if body_subsystem is not None
            else get_bound_body_subsystem()
        )
        self._avatar_trace_logger = TraceLogger()
        self._submitted_performance_ids: set[str] = set()
        self._submitted_performance_order: deque[str] = deque()
        self._submitted_body_request_ids: set[str] = set()
        self._submitted_body_request_order: deque[str] = deque()

    async def execute(self, action_plan: ActionPlan) -> ActionExecutionResult | None:
        if action_plan.action_type == ActionType.SPEAK:
            await self._present_speech_to_body(action_plan)
            return await super().execute(action_plan)

        body_request = action_plan.metadata.get("body_expression_request")
        if action_plan.action_type == ActionType.CHANGE_EXPRESSION and isinstance(
            body_request,
            BodyExpressionRequest,
        ):
            if await self._submit_body_request(action_plan, body_request):
                return None

        if (
            action_plan.action_type == ActionType.MOVE
            and isinstance(body_request, BodyExpressionRequest)
            and body_request.request_id in self._submitted_body_request_ids
        ):
            self._avatar_trace_logger.write(
                "execute_action_usecase:body_legacy_move_skipped",
                action_id=action_plan.action_id,
                request_id=body_request.request_id,
                reason="body_expression_already_submitted",
            )
            return None

        avatar_output = self._avatar_output
        if avatar_output is None or action_plan.action_type not in {
            ActionType.CHANGE_EXPRESSION,
            ActionType.MOVE,
        }:
            return await super().execute(action_plan)

        performance_id = action_plan.metadata.get("avatar_performance_id")
        performance = action_plan.metadata.get("avatar_performance_plan")
        performance_managed = (
            action_plan.metadata.get("avatar_performance_managed") is True
            and isinstance(performance_id, str)
            and bool(performance_id.strip())
        )

        if performance_managed and performance_id in self._submitted_performance_ids:
            self._avatar_trace_logger.write(
                "execute_action_usecase:avatar_individual_action_skipped",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                performance_id=performance_id,
                reason="performance_already_submitted",
            )
            return None

        if performance_managed and isinstance(performance, AvatarPerformancePlan):
            submit_performance = getattr(avatar_output, "submit_performance", None)
            if callable(submit_performance):
                try:
                    await submit_performance(performance)
                except Exception as error:
                    self._avatar_trace_logger.warning(
                        "execute_action_usecase:avatar_performance_failed",
                        action_id=action_plan.action_id,
                        source_activity_id=action_plan.source_activity_id,
                        output_unit_id=action_plan.output_unit_id,
                        performance_id=performance.performance_id,
                        error_type=type(error).__name__,
                        error_message=str(error),
                    )
                else:
                    self._remember_submitted_performance(performance.performance_id)
                    self._avatar_trace_logger.write(
                        "execute_action_usecase:avatar_performance_submitted",
                        action_id=action_plan.action_id,
                        source_activity_id=action_plan.source_activity_id,
                        output_unit_id=action_plan.output_unit_id,
                        performance_id=performance.performance_id,
                        track_count=len(performance.tracks),
                        segment_count=len(performance.segments),
                    )
                    return None

        try:
            if action_plan.action_type == ActionType.CHANGE_EXPRESSION:
                await avatar_output.set_expression(action_plan.text)
            else:
                await avatar_output.play_gesture(action_plan.text)
        except Exception as error:
            self._avatar_trace_logger.warning(
                "execute_action_usecase:avatar_output_failed",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                source_activity_id=action_plan.source_activity_id,
                output_unit_id=action_plan.output_unit_id,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return None

        self._avatar_trace_logger.write(
            "execute_action_usecase:avatar_output_finished",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
            source_activity_id=action_plan.source_activity_id,
            output_unit_id=action_plan.output_unit_id,
            avatar_command=action_plan.text,
        )
        return None

    async def _submit_body_request(
        self,
        action_plan: ActionPlan,
        request: BodyExpressionRequest,
    ) -> bool:
        body = self._body_subsystem
        if body is None:
            return False
        context = action_plan.metadata.get("body_activity_context")
        try:
            if isinstance(context, BodyActivityContext):
                await body.update_activity_context(context)
            await body.request_expression(request)
        except Exception as error:
            self._avatar_trace_logger.warning(
                "execute_action_usecase:body_expression_failed",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                output_unit_id=action_plan.output_unit_id,
                request_id=request.request_id,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return False
        self._remember_submitted_body_request(request.request_id)
        self._avatar_trace_logger.write(
            "execute_action_usecase:body_expression_submitted",
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            output_unit_id=action_plan.output_unit_id,
            request_id=request.request_id,
        )
        return True

    async def _present_speech_to_body(self, action_plan: ActionPlan) -> None:
        body = self._body_subsystem
        if body is None:
            return
        prepared_audio = action_plan.metadata.get("prepared_audio")
        duration_ms = self._prepared_audio_duration_ms(prepared_audio)
        audio_reference = f"estimated://speech/{action_plan.action_id}"
        if isinstance(prepared_audio, bytes):
            audio_reference = f"memory://prepared-audio/{action_plan.action_id}"
        if duration_ms is None:
            duration_ms = round(
                self._estimate_speech_duration_seconds(action_plan.text) * 1000
            )
        raw_emphasis = action_plan.metadata.get("speech_emphasis", ())
        emphasis = (
            tuple(
                item for item in raw_emphasis if isinstance(item, SpeechEmphasis)
            )
            if isinstance(raw_emphasis, (tuple, list))
            else ()
        )
        request = SpeechPresentationRequest(
            source_activity_id=action_plan.source_activity_id,
            output_unit_id=action_plan.output_unit_id,
            text=action_plan.text,
            audio_reference=audio_reference,
            duration_ms=max(100, min(600_000, duration_ms)),
            emphasis=emphasis,
            presentation_id=action_plan.action_id,
        )
        try:
            await body.present_speech(request)
        except Exception as error:
            self._avatar_trace_logger.warning(
                "execute_action_usecase:body_speech_presentation_failed",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return
        self._avatar_trace_logger.write(
            "execute_action_usecase:body_speech_presented",
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            duration_ms=request.duration_ms,
            prepared_audio=isinstance(prepared_audio, bytes),
        )

    @staticmethod
    def _prepared_audio_duration_ms(value: object) -> int | None:
        if not isinstance(value, bytes) or not value:
            return None
        try:
            with open_wave(BytesIO(value), "rb") as wav:
                frame_rate = wav.getframerate()
                if frame_rate <= 0:
                    return None
                return max(100, round(wav.getnframes() / frame_rate * 1000))
        except (WaveError, EOFError, OSError):
            return None

    def _remember_submitted_performance(self, performance_id: str) -> None:
        self._remember_bounded(
            performance_id,
            values=self._submitted_performance_ids,
            order=self._submitted_performance_order,
            limit=self._MAX_TRACKED_PERFORMANCES,
        )

    def _remember_submitted_body_request(self, request_id: str) -> None:
        self._remember_bounded(
            request_id,
            values=self._submitted_body_request_ids,
            order=self._submitted_body_request_order,
            limit=self._MAX_TRACKED_BODY_REQUESTS,
        )

    @staticmethod
    def _remember_bounded(
        value: str,
        *,
        values: set[str],
        order: deque[str],
        limit: int,
    ) -> None:
        if value in values:
            return
        if len(order) >= limit:
            discarded = order.popleft()
            values.discard(discarded)
        order.append(value)
        values.add(value)
