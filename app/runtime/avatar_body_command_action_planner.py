from __future__ import annotations

from dataclasses import replace

from app.domain.actions import ActionPlan
from app.domain.activities import Activity
from app.domain.character_response import CharacterResponse
from app.runtime.avatar_performance_action_planner import (
    AvatarPerformanceActionPlanner,
)
from app.runtime.body_motion_request_resolver import (
    BodyMotionRequestResolver,
)


class AvatarBodyCommandActionPlanner(AvatarPerformanceActionPlanner):
    """構造化された身体入力をCore BodyのMotionRequestへ付与する。

    クラス名はComposition Root互換のため維持するが、完成済み`body_actions`や
    Motion名は生成しない。
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._body_motion_request_resolver = BodyMotionRequestResolver()

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
        motion_request = self._body_motion_request_resolver.resolve(activity)
        if motion_request is None or not plans:
            return plans
        if motion_request.motion_id is None:
            motion_request = replace(
                motion_request,
                motion_id=f"{activity.activity_id}:{output_unit_id}:body-motion",
            )
        first = plans[0]
        metadata = dict(first.metadata)
        metadata["body_motion_request"] = motion_request
        metadata.pop("avatar_body_actions", None)
        plans[0] = replace(first, metadata=metadata)
        return plans
