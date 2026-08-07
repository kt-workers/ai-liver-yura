from __future__ import annotations

from app.domain.activities import ActivityType
from app.domain.behavior import (
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
    SituationAnalysis,
)
from app.domain.body_instruction import (
    BODY_ACTION_INTENT_CONSTRAINT,
    BODY_EXPRESSION_ACTIVITY_TYPE,
    BodyInstruction,
)
from app.runtime.behavior_planner import BehaviorPlanner


class BodyAwareBehaviorPlanner(BehaviorPlanner):
    """Validated Internal Directiveが選んだ身体行動だけをRuntimeへ射影する。"""

    def plan_from_analysis(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> ActivityPlan:
        instruction = self._directive_body_action_intent(analysis)
        if instruction is None:
            return super().plan_from_analysis(context, analysis)

        constraints = dict(analysis.constraints)
        constraints[BODY_ACTION_INTENT_CONSTRAINT] = instruction.as_context()
        # 既存#202のpreflight/MOVE実行境界へ渡す移行用projection。
        # 入力意味から生成せず、Validated Internal Directiveだけをsourceにする。
        constraints["_body_instruction"] = instruction.as_context()
        return ActivityPlan(
            decision=BehaviorDecision.START_ACTIVITY,
            activity_type=ActivityType.BODY_EXPRESSION_LOOP.value,
            goal=analysis.goal or "Internal Directiveで選択した身体行動を実現する",
            required_capability=None,
            provider_plugin_id="runtime",
            operation=ActivityOperation.START,
            constraints=constraints,
            planner_constraints=(
                "Internal Directiveのbody_action_intentを意識的行動の正本として扱う",
                "StructuredInputMeaningのbody_instructionからBody実行を直接生成しない",
                "Character出力とBody出力はそれぞれ同じValidated Internal Directiveに従う",
                "Raw User Textやモーション名をBody Controllerへ渡さない",
            ),
            speech_act=analysis.speech_act,
            conversation_phase=analysis.conversation_phase,
            initiative_level=analysis.initiative_level,
            negated=analysis.negated,
            hypothetical=analysis.hypothetical,
            past_reference=analysis.past_reference,
            knowledge_question=False,
            confidence=analysis.confidence,
            reason="validated_internal_directive_body_action",
            planner_type="internal_directive_body_action",
        )

    @staticmethod
    def _directive_body_action_intent(
        analysis: SituationAnalysis,
    ) -> BodyInstruction | None:
        envelope = analysis.constraints.get("_internal_directive")
        if not isinstance(envelope, dict):
            return None
        internal = envelope.get("internal_directive")
        if not isinstance(internal, dict):
            return None
        activity_intent = internal.get("activity_intent")
        if not isinstance(activity_intent, dict):
            return None
        if str(activity_intent.get("activity_type") or "") != BODY_EXPRESSION_ACTIVITY_TYPE:
            return None
        if str(activity_intent.get("operation") or "") != "start":
            return None
        constraints = activity_intent.get("constraints")
        if not isinstance(constraints, dict):
            return None
        return BodyInstruction.from_context(
            constraints.get(BODY_ACTION_INTENT_CONSTRAINT)
        )


__all__ = ["BodyAwareBehaviorPlanner"]
