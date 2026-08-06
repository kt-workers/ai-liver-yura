from __future__ import annotations

from collections.abc import Iterable, Mapping

from app.domain.activities import Activity
from app.domain.interaction_intention import InteractionIntention


class BodyInteractionIntentionResolver:
    """Activityに保持されたInteraction Intentionを互換位置から復元する。

    保存位置の探索だけを担当し、意図の表現射影やBody Context生成は行わない。
    """

    def resolve(self, activity: Activity) -> InteractionIntention | None:
        for candidate in self._candidates(activity):
            intention = InteractionIntention.from_context(candidate)
            if intention is not None:
                return intention
        return None

    def _candidates(self, activity: Activity) -> Iterable[object]:
        yield activity.context.get("interaction_intention")

        event_payload = activity.context.get("event_payload")
        if isinstance(event_payload, Mapping):
            yield event_payload.get("interaction_intention")
            event_memory = event_payload.get("memory")
            if isinstance(event_memory, Mapping):
                yield event_memory.get("interaction_intention")
            event_plan = event_payload.get("behavior_plan")
            if isinstance(event_plan, Mapping):
                yield from self._plan_candidates(event_plan)

        behavior_plan = activity.context.get("behavior_plan")
        if isinstance(behavior_plan, Mapping):
            yield from self._plan_candidates(behavior_plan)

        memory = activity.context.get("memory")
        if isinstance(memory, Mapping):
            yield memory.get("interaction_intention")

        execution_result = activity.context.get("activity_execution_result")
        result_constraints = getattr(execution_result, "constraints", None)
        if isinstance(result_constraints, Mapping):
            yield result_constraints.get("_interaction_intention")

    @staticmethod
    def _plan_candidates(plan: Mapping[str, object]) -> tuple[object, ...]:
        constraints = plan.get("constraints")
        constraint_intention = (
            constraints.get("_interaction_intention")
            if isinstance(constraints, Mapping)
            else None
        )
        return plan.get("interaction_intention"), constraint_intention
