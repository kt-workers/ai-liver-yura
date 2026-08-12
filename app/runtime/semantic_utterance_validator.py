from __future__ import annotations

from app.domain.character_response import ResponseContext
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.domain.semantic_validation import SemanticPlanValidationResult
from app.runtime.response_semantics_planner import ResponseSemanticsPlanner
from app.runtime.semantic_discourse_context import project_semantic_discourse_context


class SemanticUtteranceValidator:
    """Character生成前にSemantic Planをstructured facts由来の正規Planと照合する。"""

    def __init__(self, planner: ResponseSemanticsPlanner | None = None) -> None:
        self._planner = planner or ResponseSemanticsPlanner()

    def validate(
        self,
        context: ResponseContext,
        plan: SemanticUtterancePlan,
    ) -> SemanticPlanValidationResult:
        canonical = project_semantic_discourse_context(
            context,
            self._planner.plan(context),
        )
        differences: list[str] = []

        if plan.speech_act != canonical.speech_act:
            differences.append("speech_act_mismatch")
        if plan.target != canonical.target:
            differences.append("target_mismatch")
        if plan.propositions != canonical.propositions:
            differences.append("proposition_mismatch")
        if plan.required_content != canonical.required_content:
            differences.append("required_content_mismatch")
        if plan.optional_content != canonical.optional_content:
            differences.append("optional_content_mismatch")
        if plan.forbidden_additions != canonical.forbidden_additions:
            differences.append("forbidden_additions_mismatch")
        if plan.response_length != canonical.response_length:
            differences.append("response_length_mismatch")
        if plan.self_disclosure != canonical.self_disclosure:
            differences.append("self_disclosure_mismatch")
        if plan.question_budget != canonical.question_budget:
            differences.append("question_budget_mismatch")
        if plan.new_direction_budget != canonical.new_direction_budget:
            differences.append("new_direction_budget_mismatch")
        if plan.interpersonal != canonical.interpersonal:
            differences.append("interpersonal_content_mismatch")
        if dict(plan.discourse_context) != dict(canonical.discourse_context):
            differences.append("discourse_context_mismatch")

        if differences:
            return SemanticPlanValidationResult(
                accepted=False,
                reason="semantic_plan_inconsistent_with_structured_facts",
                differences=tuple(differences),
            )
        return SemanticPlanValidationResult(
            accepted=True,
            reason="semantic_plan_consistent",
        )
