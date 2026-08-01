from __future__ import annotations

from dataclasses import replace

from app.domain.behavior import BehaviorPlanningContext, SituationAnalysis
from app.domain.morals import (
    ActivityCandidateExecutionBoundaryEquivalenceEvaluator,
    MoralActivityCandidateEvaluator,
    MoralActivityCandidatePreferenceShadow,
    MoralActivityCandidatePreferenceShadowEvaluator,
)
from app.domain.motivation import MotivationActivityCandidateRanker
from app.utils.trace import TraceLogger


class SituationSemanticEquivalenceShadowObserver:
    """Situation解析由来の証拠と実行境界をShadow評価へ接続する。"""

    def __init__(
        self,
        *,
        candidate_ranker: MotivationActivityCandidateRanker | None = None,
        moral_candidate_evaluator: MoralActivityCandidateEvaluator | None = None,
        shadow_evaluator: (
            MoralActivityCandidatePreferenceShadowEvaluator | None
        ) = None,
        execution_boundary_equivalence_evaluator: (
            ActivityCandidateExecutionBoundaryEquivalenceEvaluator | None
        ) = None,
        trace_logger: TraceLogger | None = None,
    ) -> None:
        self._candidate_ranker = candidate_ranker or MotivationActivityCandidateRanker()
        self._moral_candidate_evaluator = (
            moral_candidate_evaluator or MoralActivityCandidateEvaluator()
        )
        self._shadow_evaluator = (
            shadow_evaluator or MoralActivityCandidatePreferenceShadowEvaluator()
        )
        self._execution_boundary_equivalence_evaluator = (
            execution_boundary_equivalence_evaluator
            or ActivityCandidateExecutionBoundaryEquivalenceEvaluator()
        )
        self._trace_logger = trace_logger or TraceLogger()

    def observe(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> MoralActivityCandidatePreferenceShadow:
        """実候補順を変更せず、解析証拠を使った仮想評価だけを返す。"""

        pinned_activity_types = tuple(
            activity_type
            for activity_type in (
                (
                    context.active_activity_definition.activity_type
                    if context.active_activity_definition is not None
                    else None
                ),
                context.ongoing_activity_type,
            )
            if activity_type is not None
        )
        ranking = self._candidate_ranker.rank(
            context.activity_definitions,
            context.motivation,
            pinned_activity_types=pinned_activity_types,
        )
        moral_fits = self._moral_candidate_evaluator.evaluate_context(
            ranking.definitions,
            context.moral,
        )
        shadow = self._shadow_evaluator.evaluate(
            ranking.definitions,
            moral_fits,
            ranking.as_context(),
            context.moral,
            semantic_equivalence_evidence=(
                analysis.semantic_equivalence_evidence
            ),
        )
        execution_boundary_equivalence = (
            self._execution_boundary_equivalence_evaluator.evaluate(
                ranking.definitions,
                shadow.candidate_group,
                authority_role=context.authority_role,
                instruction_trusted=context.instruction_trusted,
                available_capabilities=context.available_capabilities,
            )
        )
        shadow = replace(
            shadow,
            execution_boundary_equivalence=execution_boundary_equivalence,
        )
        self._trace_logger.debug(
            "situation_evaluator:semantic_equivalence_shadow_observed",
            source_event_id=context.source_event_id,
            evaluator_type=analysis.evaluator_type,
            analysis_activity_candidate=analysis.activity_candidate,
            analysis_confidence=analysis.confidence,
            evidence_id=(
                analysis.semantic_equivalence_evidence.evidence_id
                if analysis.semantic_equivalence_evidence is not None
                else None
            ),
            semantic_equivalence_status=(
                shadow.semantic_equivalence.status.value
            ),
            semantic_equivalence_candidate_group=list(
                shadow.semantic_equivalence.candidate_group
            ),
            execution_boundary_equivalence_status=(
                shadow.execution_boundary_equivalence.status.value
            ),
            authority_equivalence_status=(
                shadow.execution_boundary_equivalence.authority.status.value
            ),
            capability_equivalence_status=(
                shadow.execution_boundary_equivalence.capability.status.value
            ),
            constraint_equivalence_status=(
                shadow.execution_boundary_equivalence.constraint.status.value
            ),
            safety_equivalence_status=(
                shadow.execution_boundary_equivalence.safety.status.value
            ),
            execution_boundary_equivalence=(
                shadow.execution_boundary_equivalence.as_context()
            ),
            current_order=list(shadow.current_order),
            hypothetical_order=list(shadow.hypothetical_order),
            static_eligible=shadow.static_eligible,
            activation_permitted=shadow.activation_permitted,
            preferred_activity_type=shadow.preferred_activity_type,
            reasons=list(shadow.reasons),
        )
        return shadow
