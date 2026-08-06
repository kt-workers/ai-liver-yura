from __future__ import annotations

from app.domain.autonomous_continuation import AutonomousContinuationEvaluation
from app.domain.autonomous_interaction import (
    AutonomousInteractionComparison,
    AutonomousInteractionDecision,
)
from app.domain.causal_diagnostics import (
    CausalDecisionOutcome,
    CausalDecisionSnapshot,
    CausalDecisionStage,
)
from app.domain.character_response import ResponseContext, ResponseValidationResult
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionComparison,
)
from app.runtime.legacy_route_inventory import LegacyRouteInventory
from app.utils.trace import TraceLogger


class CausalDecisionObserver:
    """旧経路と因果経路の判断を有限な共通形式で記録する。"""

    def __init__(self, trace_logger: TraceLogger | None = None) -> None:
        self._trace_logger = trace_logger or TraceLogger()
        self._history: list[CausalDecisionSnapshot] = []

    @property
    def history(self) -> tuple[CausalDecisionSnapshot, ...]:
        return tuple(self._history)

    @property
    def latest(self) -> CausalDecisionSnapshot | None:
        return self._history[-1] if self._history else None

    def record(self, snapshot: CausalDecisionSnapshot) -> CausalDecisionSnapshot:
        self._history.append(snapshot)
        self._trace_logger.info(
            "causal_agent:decision_snapshot",
            **snapshot.as_context(),
        )
        return snapshot

    def observe_interaction_intention(
        self,
        intention: InteractionIntention,
        comparison: InteractionIntentionComparison,
    ) -> CausalDecisionSnapshot:
        outcome = (
            CausalDecisionOutcome.MATCHED
            if comparison.exact_match
            else CausalDecisionOutcome.OBSERVED
        )
        return self.record(
            CausalDecisionSnapshot(
                stage=CausalDecisionStage.INTERACTION_INTENTION,
                causal_route=LegacyRouteInventory.get(
                    "interaction_intention_appraisal"
                ),
                legacy_route=LegacyRouteInventory.get(
                    "internal_directive_to_intention_projection"
                ),
                outcome=outcome,
                reason=comparison.reason,
                intention=intention.intention.value,
                action=comparison.directive_projection.value,
                accepted=None,
                metrics={
                    "exact_match": comparison.exact_match,
                    "compatible": comparison.compatible,
                    "observation_only": intention.observation_only,
                    "confidence": intention.confidence,
                },
            )
        )

    def observe_autonomous_start(
        self,
        decision: AutonomousInteractionDecision,
        comparison: AutonomousInteractionComparison,
    ) -> CausalDecisionSnapshot:
        if comparison.conservative_start_allowed:
            outcome = CausalDecisionOutcome.CONSERVATIVE_ALLOWED
        elif comparison.expansion_blocked:
            outcome = CausalDecisionOutcome.EXPANSION_BLOCKED
        elif comparison.causal_vetoed_legacy_start:
            outcome = CausalDecisionOutcome.CAUSAL_VETO
        else:
            outcome = CausalDecisionOutcome.MATCHED
        return self.record(
            CausalDecisionSnapshot(
                stage=CausalDecisionStage.AUTONOMOUS_START,
                causal_route=LegacyRouteInventory.get(
                    "autonomous_interaction_decider"
                ),
                legacy_route=LegacyRouteInventory.get(
                    "drive_should_start_autonomous_talk"
                ),
                outcome=outcome,
                reason=decision.reason,
                intention=decision.interaction_intention.intention.value,
                action=decision.action.value,
                accepted=comparison.conservative_start_allowed,
                metrics={
                    "legacy_drive_ready": comparison.legacy_drive_ready,
                    "causal_should_start": comparison.causal_should_start,
                    "matched": comparison.matched,
                    "confidence": decision.confidence,
                },
            )
        )

    def observe_character_claim(
        self,
        context: ResponseContext,
        result: ResponseValidationResult,
    ) -> CausalDecisionSnapshot:
        intention = context.interaction_intention
        return self.record(
            CausalDecisionSnapshot(
                stage=CausalDecisionStage.CHARACTER_CLAIM,
                causal_route=LegacyRouteInventory.get(
                    "deterministic_fact_validator"
                ),
                legacy_route=LegacyRouteInventory.get(
                    "character_self_reported_claims"
                ),
                outcome=(
                    CausalDecisionOutcome.ACCEPTED
                    if result.accepted
                    else CausalDecisionOutcome.REJECTED
                ),
                reason=result.reason,
                intention=(
                    intention.intention.value if intention is not None else None
                ),
                action=context.operation,
                accepted=result.accepted,
                metrics={
                    "execution_status": context.status.value,
                    "activity_type": context.activity_type,
                    "invalid_claim_count": len(result.invalid_claims),
                    "extracted_claim_count": len(result.extracted_claims),
                    "difference_count": len(result.claim_differences),
                },
            )
        )

    def observe_autonomous_continuation(
        self,
        evaluation: AutonomousContinuationEvaluation,
    ) -> CausalDecisionSnapshot:
        return self.record(
            CausalDecisionSnapshot(
                stage=CausalDecisionStage.AUTONOMOUS_CONTINUATION,
                causal_route=LegacyRouteInventory.get(
                    "autonomous_topic_evaluate_completion"
                )
                if self._has_route("autonomous_topic_evaluate_completion")
                else LegacyRouteInventory.get(
                    "autonomous_interaction_decider"
                ),
                legacy_route=LegacyRouteInventory.get(
                    "autonomous_topic_should_complete_tuple"
                ),
                outcome=(
                    CausalDecisionOutcome.COMPLETE
                    if evaluation.should_complete
                    else CausalDecisionOutcome.CONTINUE
                ),
                reason=evaluation.reason,
                action=evaluation.action.value,
                accepted=evaluation.should_complete,
                metrics={
                    "continuation_strength": evaluation.continuation_strength,
                    "turn_count": evaluation.turn_count,
                    "waiting_for_user": evaluation.waiting_for_user,
                    "hard_limit_reached": evaluation.hard_limit_reached,
                },
            )
        )

    def observe_autonomous_completion(
        self,
        *,
        topic_status: str,
        reason: str,
    ) -> CausalDecisionSnapshot:
        return self.record(
            CausalDecisionSnapshot(
                stage=CausalDecisionStage.AUTONOMOUS_COMPLETION,
                causal_route=LegacyRouteInventory.get(
                    "autonomous_interaction_decider"
                ),
                outcome=CausalDecisionOutcome.COMPLETE,
                reason=reason,
                action=topic_status,
                accepted=True,
            )
        )

    @staticmethod
    def _has_route(name: str) -> bool:
        try:
            LegacyRouteInventory.get(name)
        except KeyError:
            return False
        return True
