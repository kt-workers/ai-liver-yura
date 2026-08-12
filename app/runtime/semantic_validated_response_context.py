from __future__ import annotations

from dataclasses import replace

from app.domain.activities import Activity
from app.domain.character_response import ResponseContext
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.internal_state_response_context import InternalStateAwareResponseContextBuilder
from app.runtime.semantic_utterance_validator import SemanticUtteranceValidator
from app.utils.trace import TraceLogger


class SemanticValidatedResponseContextBuilder(InternalStateAwareResponseContextBuilder):
    """Semantic PlanをCharacterへ渡す前にstructured factsとの整合性を確定する。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._semantic_validator = SemanticUtteranceValidator()
        self._semantic_validation_trace_logger = TraceLogger()

    def build(self, activity: Activity) -> ResponseContext:
        context = super().build(activity)
        plan = SemanticUtterancePlan.from_context(
            context.memory.get("semantic_utterance_plan")
        )
        if plan is None:
            return context

        result = self._semantic_validator.validate(context, plan)
        memory = dict(context.memory)
        memory["semantic_validation"] = result.as_context()
        projected = replace(context, memory=memory)
        self._semantic_validation_trace_logger.debug(
            "semantic_utterance_validator:completed",
            source_activity_id=activity.activity_id,
            accepted=result.accepted,
            reason=result.reason,
            differences=list(result.differences),
        )
        if not result.accepted:
            raise ValueError(
                "SemanticUtterancePlanがstructured factsと整合しません: "
                + ",".join(result.differences)
            )
        return projected
