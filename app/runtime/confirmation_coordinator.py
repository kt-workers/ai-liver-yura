from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from app.domain.behavior import (
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
)
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
)
from app.domain.events import AgentEvent
from app.domain.pending_confirmation import (
    ConfirmationResolutionKind,
    PendingConfirmation,
)
from app.runtime.behavior_planner import ActivityPlanValidator
from app.runtime.pending_confirmation import (
    ConfirmationResolver,
    PendingConfirmationManager,
)
from app.utils.trace import TraceLogger


@dataclass(frozen=True)
class ConfirmationRoutingResult:
    event: AgentEvent
    planning_context: BehaviorPlanningContext
    plan: ActivityPlan | None
    situation_payload: dict[str, object]
    confirmation_payload: dict[str, object]
    terminal_event: AgentEvent | None = None


class ConfirmationCoordinator:
    """確認待ち入力の解決と確認用Eventの構築を調停する。"""

    def __init__(
        self,
        *,
        manager: PendingConfirmationManager,
        resolver: ConfirmationResolver,
        validator: ActivityPlanValidator,
        conversation_fallback: Callable[[AgentEvent], AgentEvent],
        plan_payload: Callable[[ActivityPlan], dict[str, object]],
        trace_logger: TraceLogger,
    ) -> None:
        self._manager = manager
        self._resolver = resolver
        self._validator = validator
        self._conversation_fallback = conversation_fallback
        self._plan_payload = plan_payload
        self._trace_logger = trace_logger

    @property
    def pending(self) -> PendingConfirmation | None:
        return self._manager.current()

    def route_pending(
        self,
        event: AgentEvent,
        planning_context: BehaviorPlanningContext,
    ) -> ConfirmationRoutingResult | None:
        pending = self._manager.current()
        if pending is None:
            return None
        event = replace(
            event,
            trace_context=event.trace_context.derive(
                parent_trace_id=pending.original_trace_id,
                confirmation_id=pending.confirmation_id,
            ),
        )
        planning_context = replace(
            planning_context,
            trace_context=event.trace_context,
        )
        resolution = self._resolver.resolve(
            planning_context.user_text,
            pending,
            trace_context=event.trace_context,
        )
        if resolution.kind == ConfirmationResolutionKind.NEW_REQUEST:
            self._manager.resolve(
                pending,
                resolution,
                resolution_event_id=event.event_id,
                trace_context=event.trace_context,
            )
            return ConfirmationRoutingResult(
                event=event,
                planning_context=planning_context,
                plan=None,
                situation_payload={},
                confirmation_payload={},
            )
        if resolution.kind == ConfirmationResolutionKind.AFFIRMATIVE:
            resolved = self._manager.resolve(
                pending,
                resolution,
                resolution_event_id=event.event_id,
                trace_context=event.trace_context,
            )
            plan = self._confirmed_plan(resolved.candidate_plan)
            snapshot_analysis = resolved.context_snapshot.get("situation_analysis")
            situation_payload = (
                dict(snapshot_analysis)
                if isinstance(snapshot_analysis, dict)
                else {}
            )
            confirmation_payload = self._confirmation_payload(
                resolved,
                resolution=resolution.kind.value,
                final_plan=plan,
            )
            self._trace_logger.debug(
                "pending_confirmation:confirmed_plan",
                confirmation_id=resolved.confirmation_id,
                final_plan=plan,
                plugin_handler_will_be_called=plan.required_capability is not None,
            )
            return ConfirmationRoutingResult(
                event=event,
                planning_context=planning_context,
                plan=plan,
                situation_payload=situation_payload,
                confirmation_payload=confirmation_payload,
            )
        if resolution.kind in {
            ConfirmationResolutionKind.NEGATIVE,
            ConfirmationResolutionKind.CANCEL,
        }:
            resolved = self._manager.resolve(
                pending,
                resolution,
                resolution_event_id=event.event_id,
                trace_context=event.trace_context,
            )
            terminal = self._response_event(
                event,
                resolved,
                resolution=resolution.kind.value,
                waiting=False,
            )
            return ConfirmationRoutingResult(
                event=event,
                planning_context=planning_context,
                plan=None,
                situation_payload={},
                confirmation_payload={},
                terminal_event=terminal,
            )
        revised = self._manager.revise(
            pending,
            resolution,
            source_event_id=event.event_id,
            constraint_validation=self._validator.validate_constraints,
        )
        terminal = self._response_event(
            event,
            revised or pending,
            resolution=(
                resolution.kind.value
                if revised is not None
                else "max_attempts_reached"
            ),
            waiting=revised is not None,
        )
        return ConfirmationRoutingResult(
            event=event,
            planning_context=planning_context,
            plan=None,
            situation_payload={},
            confirmation_payload={},
            terminal_event=terminal,
        )

    def request_confirmation(
        self,
        event: AgentEvent,
        plan: ActivityPlan,
        *,
        current_ongoing_activity_id: str | None,
        situation_payload: dict[str, object],
    ) -> AgentEvent:
        created = self._manager.create(
            plan,
            source_event_id=event.event_id,
            current_ongoing_activity_id=current_ongoing_activity_id,
            context_snapshot={"situation_analysis": situation_payload},
            trace_context=event.trace_context,
        )
        return self._response_event(
            event,
            created,
            resolution=None,
            waiting=True,
        )

    @staticmethod
    def _confirmed_plan(plan: ActivityPlan) -> ActivityPlan:
        if plan.requested_new_activity:
            decision = BehaviorDecision.SWITCH_ACTIVITY
        elif plan.operation == ActivityOperation.START:
            decision = BehaviorDecision.START_ACTIVITY
        elif plan.operation in {ActivityOperation.CONTINUE, ActivityOperation.STOP}:
            decision = BehaviorDecision.CONTINUE_ACTIVITY
        else:
            decision = BehaviorDecision.CONVERSATION
        return replace(
            plan,
            decision=decision,
            activity_type=(
                "conversation"
                if decision == BehaviorDecision.CONVERSATION
                else plan.activity_type
            ),
            required_capability=(
                None
                if decision == BehaviorDecision.CONVERSATION
                else plan.required_capability
            ),
            provider_plugin_id=(
                None
                if decision == BehaviorDecision.CONVERSATION
                else plan.provider_plugin_id
            ),
            planner_constraints=tuple(
                item
                for item in plan.planner_constraints
                if "確認" not in item and "低確信度" not in item
            )
            + ("確認解決後もCapabilityを再検証する",),
            confidence=1.0,
            reason=f"confirmed:{plan.reason}",
        )

    def _response_event(
        self,
        event: AgentEvent,
        pending: PendingConfirmation,
        *,
        resolution: str | None,
        waiting: bool,
    ) -> AgentEvent:
        payload = self._confirmation_payload(pending, resolution=resolution)
        summary = pending.question if waiting else self._resolution_summary(resolution)
        conversation_plan = ActivityPlan(
            decision=(
                BehaviorDecision.ASK_CONFIRMATION
                if waiting
                else BehaviorDecision.CONVERSATION
            ),
            activity_type="confirmation" if waiting else "conversation",
            goal=summary,
            operation=ActivityOperation.DISCUSS,
            planner_constraints=(
                "確認対象を変更しない",
                "確認前のActivity実行・停止・切替を主張しない",
                "内部用語を発話しない",
            ),
            confidence=pending.candidate_confidence,
            reason=resolution or "pending_confirmation_created",
        )
        result = ActivityExecutionResult(
            activity_type="confirmation",
            operation=pending.candidate_operation,
            status=(
                ActivityExecutionStatus.WAITING_INPUT
                if waiting
                else ActivityExecutionStatus.CANCELED
            ),
            payload={"summary": summary, "question": pending.question},
            failure_reason=None if waiting else resolution,
            constraints=dict(pending.candidate_constraints),
            source_event_id=event.event_id,
        )
        routed = self._conversation_fallback(event)
        return replace(
            routed,
            payload={
                **routed.payload,
                "behavior_plan": self._plan_payload(conversation_plan),
                "activity_execution_result": result,
                **payload,
            },
        )

    def _confirmation_payload(
        self,
        pending: PendingConfirmation,
        *,
        resolution: str | None,
        final_plan: ActivityPlan | None = None,
    ) -> dict[str, object]:
        return {
            "pending_confirmation": {
                "confirmation_id": pending.confirmation_id,
                "source_event_id": pending.source_event_id,
                "resolution_event_id": pending.resolution_event_id,
                "confirmation_type": pending.confirmation_type.value,
                "status": pending.status.value,
                "candidate_activity_type": pending.candidate_activity_type,
                "candidate_operation": pending.candidate_operation,
                "candidate_goal": pending.candidate_goal,
                "candidate_constraints": dict(pending.candidate_constraints),
                "candidate_confidence": pending.candidate_confidence,
                "candidate_constraints_schema_version": (
                    pending.candidate_constraints_schema_version
                ),
                "current_ongoing_activity_id": pending.current_ongoing_activity_id,
                "question": pending.question,
                "attempt_count": pending.attempt_count,
                "max_attempts": pending.max_attempts,
                "resolution": resolution,
                "final_behavior_plan": (
                    self._plan_payload(final_plan) if final_plan is not None else None
                ),
                "final_behavior_plan_id": (
                    f"{pending.confirmation_id}:{pending.resolution_event_id}"
                    if final_plan is not None
                    and pending.resolution_event_id is not None
                    else None
                ),
                "original_trace_id": pending.original_trace_id,
                "resolution_trace_id": pending.resolution_trace_id,
                "parent_trace_id": pending.parent_trace_id,
            }
        }

    @staticmethod
    def _resolution_summary(resolution: str | None) -> str:
        if resolution == ConfirmationResolutionKind.NEGATIVE.value:
            return "確認候補は実行せず、現在の状態を維持する"
        if resolution == ConfirmationResolutionKind.CANCEL.value:
            return "確認を取り消し、候補は実行しない"
        return "意図を確定できなかったため、候補は実行しない"
