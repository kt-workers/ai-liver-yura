from __future__ import annotations

from app.domain.cognitive_direction import ValidatedActionPlan
from app.runtime.separated_situation_evaluator import (
    SeparatedSituationEvaluationAdapter,
)


class BodyAwareSeparatedSituationEvaluationAdapter(SeparatedSituationEvaluationAdapter):
    """Activityを選んだTurnでもValidated Internal Directiveを失わない。

    CharacterとBodyが同じ意識的行動決定を参照できるよう、conversation以外でも
    `_internal_directive` envelopeをActivity constraintsへ保持する。
    """

    @staticmethod
    def _legacy_situation_payload(plan: ValidatedActionPlan) -> dict[str, object]:
        payload = SeparatedSituationEvaluationAdapter._legacy_situation_payload(plan)
        constraints_value = payload.get("constraints")
        constraints = (
            dict(constraints_value) if isinstance(constraints_value, dict) else {}
        )
        constraints["_internal_directive"] = plan.as_context()
        payload["constraints"] = constraints
        return payload


__all__ = ["BodyAwareSeparatedSituationEvaluationAdapter"]
