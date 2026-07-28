from __future__ import annotations

from dataclasses import asdict, replace

from app.core.plugins import PluginManager
from app.core.plugins.user_request import UserRequestKind, interpret_user_request
from app.domain.behavior import ActivityPlan
from app.domain.events import AgentEvent
from app.utils.trace import TraceLogger


def plan_payload(plan: ActivityPlan) -> dict[str, object]:
    payload = asdict(plan)
    payload["decision"] = plan.decision.value
    payload["operation"] = plan.operation.value if plan.operation else None
    payload["speech_act"] = plan.speech_act.value
    payload["ongoing_input_decision"] = (
        plan.ongoing_input_decision.value
        if plan.ongoing_input_decision is not None
        else None
    )
    return payload


def ongoing_transition_payload(
    plan: ActivityPlan | None,
    *,
    current_status: str | None,
    stopped: bool = False,
    transition_result: str | None = None,
) -> dict[str, object]:
    if plan is None:
        return {}
    return {
        "ongoing_input_decision": (
            plan.ongoing_input_decision.value
            if plan.ongoing_input_decision is not None
            else None
        ),
        "current_activity_status": current_status,
        "current_activity_preserved": plan.current_activity_preserved and not stopped,
        "current_activity_paused": plan.current_activity_paused,
        "current_activity_stopped": stopped,
        "requested_new_activity": plan.requested_new_activity,
        "transition_result": transition_result,
    }


class BehaviorFallbackRouter:
    """Plugin利用可否を付加し、安全な会話fallback Eventを構築する。"""

    def __init__(
        self,
        *,
        plugin_manager: PluginManager | None,
        trace_logger: TraceLogger,
    ) -> None:
        self._plugin_manager = plugin_manager
        self._trace_logger = trace_logger

    def with_plugin_availability(self, event: AgentEvent) -> AgentEvent:
        capabilities = self._capabilities()
        interpretation = interpret_user_request(str(event.payload.get("text") or ""))
        if interpretation.kind == UserRequestKind.EXECUTION:
            self._trace_logger.info(
                "runtime_coordinator:execution_request_unmatched",
                confidence=interpretation.confidence,
                reason=interpretation.reason,
                available_capability_count=len(capabilities),
            )
            return self.with_execution_fallback(
                event,
                contexts=[],
                reason=interpretation.reason,
                confidence=interpretation.confidence,
            )
        return replace(
            event,
            payload={
                **event.payload,
                "available_plugin_capabilities": capabilities,
                "user_request_kind": interpretation.kind.value,
                "execution_performed": False,
            },
        )

    def with_execution_fallback(
        self,
        event: AgentEvent,
        *,
        contexts: list[dict[str, object]],
        reason: str,
        confidence: float,
    ) -> AgentEvent:
        capabilities = self._capabilities()
        self._trace_logger.info(
            "runtime_coordinator:conversation_fallback_selected",
            reason=reason,
            confidence=confidence,
            available_capability_count=len(capabilities),
        )
        return replace(
            event,
            payload={
                **event.payload,
                "available_plugin_capabilities": capabilities,
                "plugin_contexts": contexts,
                "user_request_kind": UserRequestKind.EXECUTION.value,
                "execution_request_unmatched": True,
                "execution_performed": False,
                "execution_match_confidence": confidence,
                "execution_match_reason": reason,
                "safe_conversation_fallback": "今はそれを一緒にできないんだ。別のお話をしよう。",
                "available_alternative": "文字での通常会話",
            },
        )

    def _capabilities(self) -> list[str]:
        return (
            sorted(self._plugin_manager.list_capabilities())
            if self._plugin_manager is not None
            else []
        )
