from __future__ import annotations

from dataclasses import replace

from app.domain.actions import ActionPlan, ActionType
from app.domain.activities import Activity
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.domain.character_response import CharacterResponse
from app.runtime.avatar_performance_action_planner import (
    AvatarPerformanceActionPlanner,
)
from app.runtime.body_spatial_command_resolver import BodySpatialCommandResolver


class AvatarBodyCommandActionPlanner(AvatarPerformanceActionPlanner):
    """構造化されたアバター身体命令を最初のBody要求へ付与する。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._avatar_body_command_resolver = BodySpatialCommandResolver()

    def _reaction_action_plans(
        self,
        activity: Activity,
        response: CharacterResponse | None,
        *,
        fallback_speech: str,
        output_unit_id: str,
        base_metadata: dict[str, object],
        skip_topic_memory: bool,
    ) -> list[ActionPlan]:
        plans = super()._reaction_action_plans(
            activity,
            response,
            fallback_speech=fallback_speech,
            output_unit_id=output_unit_id,
            base_metadata=base_metadata,
            skip_topic_memory=skip_topic_memory,
        )
        body_actions = self._avatar_body_command_resolver.resolve_body_actions(activity)
        if not body_actions:
            return plans

        result: list[ActionPlan] = []
        attached = False
        for plan in plans:
            if attached or plan.action_type is not ActionType.CHANGE_EXPRESSION:
                result.append(plan)
                continue
            metadata = dict(plan.metadata)
            request = metadata.get("body_expression_request")
            if not isinstance(request, SpeechCoupledBodyExpressionRequest):
                result.append(plan)
                continue
            metadata["body_expression_request"] = replace(
                request,
                body_actions=body_actions,
            )
            metadata["avatar_body_actions"] = body_actions
            result.append(replace(plan, metadata=metadata))
            attached = True
        return result
