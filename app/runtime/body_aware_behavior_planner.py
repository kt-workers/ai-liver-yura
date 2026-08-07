from __future__ import annotations

from app.domain.activities import ActivityType
from app.domain.behavior import (
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
    SituationAnalysis,
)
from app.domain.body_instruction import BodyInstruction
from app.runtime.behavior_planner import BehaviorPlanner


class BodyAwareBehaviorPlanner(BehaviorPlanner):
    """会話意味に含まれる明示Body指示だけをRuntime Activityへ持ち上げる。"""

    def plan_from_analysis(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> ActivityPlan:
        instruction = self._explicit_body_instruction(context, analysis)
        if instruction is None:
            return super().plan_from_analysis(context, analysis)

        constraints = dict(analysis.constraints)
        constraints["_body_instruction"] = instruction.as_context()
        return ActivityPlan(
            decision=BehaviorDecision.START_ACTIVITY,
            activity_type=ActivityType.BODY_EXPRESSION_LOOP.value,
            goal="明示された身体方向を短時間のBody制約として適用する",
            required_capability=None,
            provider_plugin_id="runtime",
            operation=ActivityOperation.START,
            constraints=constraints,
            planner_constraints=(
                "Body制約の受付結果が確定する前に動作済みと主張しない",
                "明示指示を恒常的な感情・欲望・動機へ変換しない",
                "Raw User Textやモーション名をBody Controllerへ渡さない",
            ),
            speech_act=analysis.speech_act,
            conversation_phase=analysis.conversation_phase,
            initiative_level=analysis.initiative_level,
            negated=False,
            hypothetical=False,
            past_reference=False,
            knowledge_question=False,
            confidence=analysis.confidence,
            reason="explicit_body_instruction",
            planner_type="deterministic_body_instruction",
        )

    @staticmethod
    def _explicit_body_instruction(
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> BodyInstruction | None:
        if context.authority_role not in {"user", "administrator", "system"}:
            return None
        if analysis.negated or analysis.hypothetical or analysis.past_reference:
            return None
        envelope = analysis.constraints.get("_internal_directive")
        if not isinstance(envelope, dict):
            return None
        meaning = envelope.get("structured_input_meaning")
        if not isinstance(meaning, dict):
            return None
        if str(meaning.get("expected_response") or "") != "action":
            return None
        if str(meaning.get("input_speech_act") or "") not in {"command", "request"}:
            return None
        return BodyInstruction.from_context(meaning.get("body_instruction"))


__all__ = ["BodyAwareBehaviorPlanner"]
