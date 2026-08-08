from __future__ import annotations

from dataclasses import replace

from app.domain.activities import ActivityType
from app.domain.behavior import (
    ActivityDefinition,
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


def _simple_body_instruction_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "effector": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
            },
            "direction": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
            },
            "side": {
                "type": ["string", "null"],
                "maxLength": 32,
            },
            "magnitude": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
        },
        "required": ["effector", "direction", "magnitude"],
        "additionalProperties": False,
    }


def _body_action_intent_schema() -> dict[str, object]:
    schema = _simple_body_instruction_schema()
    properties = dict(schema["properties"])  # type: ignore[arg-type]
    properties["components"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 8,
        "items": _simple_body_instruction_schema(),
    }
    schema["properties"] = properties
    return schema


def _core_body_activity_definition() -> ActivityDefinition:
    """Internal Directiveが選択できるCore-owned Body Activityの正規定義。"""

    return ActivityDefinition(
        activity_type=BODY_EXPRESSION_ACTIVITY_TYPE,
        display_name="意識的なBody表現",
        required_capability=None,
        provider_plugin_id="runtime",
        description=(
            "Internal Directiveがゆら自身の意識的身体行動として選択した、"
            "モデル非依存の一時Body表現を実現する"
        ),
        supported_operations=(ActivityOperation.START,),
        semantic_descriptions=(
            "アバターBodyの頭・視線・腕などを高レベル意味に沿って一時的に動かす",
            "複数部位を同時に満たす一つの高レベルBody意図を扱う",
        ),
        constraints_schema={
            "type": "object",
            "properties": {
                BODY_ACTION_INTENT_CONSTRAINT: _body_action_intent_schema(),
                # Validated Internal Directive envelopeはBody/Characterの共通正本。
                # 内容の検証はInternal Directive Validatorが所有する。
                "_internal_directive": {"type": "object"},
            },
            "required": [BODY_ACTION_INTENT_CONSTRAINT],
            "additionalProperties": False,
        },
        constraints_schema_version="body-action-intent-v2",
    )


class BodyAwareBehaviorPlanner(BehaviorPlanner):
    """Validated Internal Directiveが選んだ身体行動だけをRuntimeへ射影する。"""

    async def evaluate_situation(
        self, context: BehaviorPlanningContext
    ) -> SituationAnalysis:
        """Core-owned Body Activityを正規候補としてSituation評価へ供給する。

        generic SituationEvaluatorの「候補外Activityを拒否する」境界は維持し、
        Bodyだけをparserで例外通過させない。Plugin RegistryにBody定義がなくても、
        Body-aware Runtime自身が所有する定義をPlanning Contextへ追加する。
        """

        if any(
            definition.activity_type == BODY_EXPRESSION_ACTIVITY_TYPE
            for definition in context.activity_definitions
        ):
            planning_context = context
        else:
            planning_context = replace(
                context,
                activity_definitions=(
                    *context.activity_definitions,
                    _core_body_activity_definition(),
                ),
            )
        return await super().evaluate_situation(planning_context)

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
                "複合body_action_intentのcomponentsは同時に満たす一つの意図として扱う",
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
