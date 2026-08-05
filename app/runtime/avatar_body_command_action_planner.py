from __future__ import annotations

from dataclasses import replace

from app.domain.actions import ActionPlan, ActionType
from app.domain.activities import Activity
from app.domain.body import BodyAttentionIntent
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.domain.character_response import CharacterResponse
from app.runtime.avatar_performance_action_planner import (
    AvatarPerformanceActionPlanner,
)
from app.runtime.body_spatial_command_resolver import BodySpatialCommandResolver


class AvatarBodyCommandActionPlanner(AvatarPerformanceActionPlanner):
    """構造化されたアバター身体命令を最初のBody要求へ付与する。

    直前のBody命令を保持し、「もう一回」のような省略指示では同じ身体Actionと
    注視方向を再利用する。記憶するのはBody向け意味命令だけで、Character発話や
    Activityそのものは再実行しない。
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._avatar_body_command_resolver = BodySpatialCommandResolver()
        self._last_body_actions: tuple[str, ...] = ()
        self._last_body_attention: BodyAttentionIntent | None = None

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
        body_actions = self._avatar_body_command_resolver.resolve_body_actions(activity)
        body_attention = self._avatar_body_command_resolver.resolve(activity)
        repeat_request = self._avatar_body_command_resolver.is_repeat_request(activity)
        if repeat_request:
            if not body_actions:
                body_actions = self._last_body_actions
            if body_attention is None:
                body_attention = self._last_body_attention

        plans = super()._reaction_action_plans(
            activity,
            response,
            fallback_speech=fallback_speech,
            output_unit_id=output_unit_id,
            base_metadata=base_metadata,
            skip_topic_memory=skip_topic_memory,
        )

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
            if not body_actions and body_attention is None:
                result.append(plan)
                continue
            metadata["body_expression_request"] = replace(
                request,
                body_actions=body_actions,
                attention=body_attention or request.attention,
            )
            if body_actions:
                metadata["avatar_body_actions"] = body_actions
            if repeat_request:
                metadata["avatar_body_repeat_previous"] = True
            result.append(replace(plan, metadata=metadata))
            attached = True

        if body_actions:
            self._last_body_actions = body_actions
        if body_attention is not None:
            self._last_body_attention = body_attention
        return result
