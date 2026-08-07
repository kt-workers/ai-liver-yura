from __future__ import annotations

from dataclasses import replace

from app.domain.body_instruction import (
    BODY_ACTION_INTENT_CONSTRAINT,
    BODY_EXPRESSION_ACTIVITY_TYPE,
    BodyInstruction,
)
from app.domain.cognitive_direction import (
    InternalDirective,
    StructuredInputMeaning,
    ValidatedActionPlan,
)
from app.runtime.internal_directive_validator import InternalDirectiveValidator


class BodyAwareInternalDirectiveValidator(InternalDirectiveValidator):
    """Internal Directiveが選択したCore Body Activityを検証する。

    StructuredInputMeaningのbody_instructionからActivity Intentを推論・復元しない。
    Bodyを動かすかどうかはInternal Directive Plannerの決定を正本とし、その決定が
    Core-owned Body Activityの型契約を満たす場合だけ後段へ通す。
    """

    def validate(
        self,
        meaning: StructuredInputMeaning,
        directive: InternalDirective,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> ValidatedActionPlan:
        augmented = self._with_core_body_activity(planning_input, directive)
        plan = super().validate(
            meaning,
            directive,
            augmented,
            character_profile=character_profile,
        )
        intent = plan.directive.activity_intent
        if intent is None or intent.activity_type != BODY_EXPRESSION_ACTIVITY_TYPE:
            return plan

        instruction = BodyInstruction.from_context(
            intent.constraints.get(BODY_ACTION_INTENT_CONSTRAINT)
        )
        if intent.operation != "start" or instruction is None:
            notes = (*plan.validation_notes, "invalid_core_body_action_intent_rejected")
            return replace(
                plan,
                directive=replace(plan.directive, activity_intent=None),
                validation_notes=notes,
            )

        normalized_constraints = dict(intent.constraints)
        normalized_constraints[BODY_ACTION_INTENT_CONSTRAINT] = instruction.as_context()
        normalized_intent = replace(intent, constraints=normalized_constraints)
        return replace(
            plan,
            directive=replace(plan.directive, activity_intent=normalized_intent),
            validation_notes=(
                *plan.validation_notes,
                "core_body_action_intent_validated",
            ),
        )

    @staticmethod
    def _with_core_body_activity(
        planning_input: dict[str, object],
        directive: InternalDirective,
    ) -> dict[str, object]:
        intent = directive.activity_intent
        if intent is None or intent.activity_type != BODY_EXPRESSION_ACTIVITY_TYPE:
            return planning_input

        copied = dict(planning_input)
        raw_activities = planning_input.get("available_activities")
        activities = (
            [dict(item) for item in raw_activities if isinstance(item, dict)]
            if isinstance(raw_activities, list)
            else []
        )
        if not any(
            str(item.get("activity_type") or "") == BODY_EXPRESSION_ACTIVITY_TYPE
            for item in activities
        ):
            activities.append(
                {
                    "activity_type": BODY_EXPRESSION_ACTIVITY_TYPE,
                    "description": "Internal Directiveが選んだ意識的Avatar Body行動",
                    "supported_operations": ["start"],
                    "source": "core_runtime",
                }
            )
        copied["available_activities"] = activities
        return copied


__all__ = ["BodyAwareInternalDirectiveValidator"]
