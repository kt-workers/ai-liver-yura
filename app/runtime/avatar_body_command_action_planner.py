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
from app.runtime.contextual_reference_resolver import (
    ContextualReferenceResolver,
    ResolvedContextualReference,
)


class AvatarBodyCommandActionPlanner(AvatarPerformanceActionPlanner):
    """構造化されたアバター身体命令を最初のBody要求へ付与する。

    「もう一回」の参照先はBody専用キャッシュでは保持しない。汎用の
    ContextualReferenceResolverがStructuredInputMeaningと会話履歴から参照元Turnを
    解決し、このPlannerは解決済みの内容を通常のBody命令として再評価する。
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._avatar_body_command_resolver = BodySpatialCommandResolver()
        self._contextual_reference_resolver = ContextualReferenceResolver()

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
        contextual_reference = self._contextual_reference_resolver.resolve(activity)

        reference_used = False
        if contextual_reference is not None:
            reference_activity = self._activity_for_reference(
                activity,
                contextual_reference,
            )
            if not body_actions:
                body_actions = self._body_actions_from_reference(contextual_reference)
                if not body_actions:
                    body_actions = (
                        self._avatar_body_command_resolver.resolve_body_actions(
                            reference_activity
                        )
                    )
                reference_used = bool(body_actions)
            if body_attention is None:
                body_attention = self._avatar_body_command_resolver.resolve(
                    reference_activity
                )
                reference_used = reference_used or body_attention is not None

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
            if contextual_reference is not None and reference_used:
                metadata["resolved_contextual_reference"] = (
                    contextual_reference.as_context()
                )
                metadata["avatar_body_repeat_previous"] = True
            result.append(replace(plan, metadata=metadata))
            attached = True
        return result

    @staticmethod
    def _activity_for_reference(
        activity: Activity,
        reference: ResolvedContextualReference,
    ) -> Activity:
        reference_context = reference.as_context()
        context = dict(activity.context)
        event_payload_value = context.get("event_payload")
        event_payload = (
            dict(event_payload_value)
            if isinstance(event_payload_value, dict)
            else {}
        )
        if reference.source_text:
            event_payload["text"] = reference.source_text
        event_payload["resolved_contextual_reference"] = reference_context
        context["event_payload"] = event_payload
        context["resolved_contextual_reference"] = reference_context
        if reference.structured_input_meaning is not None:
            context["structured_input_meaning"] = dict(
                reference.structured_input_meaning
            )
        return replace(activity, context=context)

    def _body_actions_from_reference(
        self,
        reference: ResolvedContextualReference,
    ) -> tuple[str, ...]:
        operation = reference.executed_operation
        if not isinstance(operation, dict):
            return ()
        payload_value = operation.get("payload")
        payload = dict(payload_value) if isinstance(payload_value, dict) else operation
        raw_actions = payload.get("body_actions") or payload.get("actions")
        if isinstance(raw_actions, str):
            candidates: tuple[object, ...] = (raw_actions,)
        elif isinstance(raw_actions, (list, tuple)):
            candidates = tuple(raw_actions)
        else:
            return ()
        supported = self._avatar_body_command_resolver.supported_body_actions()
        return tuple(
            normalized
            for candidate in candidates
            if (normalized := str(candidate).strip().lower()) in supported
        )
