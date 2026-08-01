from __future__ import annotations

import json

from app.domain.behavior import BehaviorPlanningContext
from app.domain.morals import MoralActivityCandidateEvaluator
from app.domain.motivation import MotivationActivityCandidateRanker


class SituationEvaluatorPromptBuilder:
    """客観的意味解析だけを要求するrole専用PromptBuilder。"""

    def __init__(
        self,
        candidate_ranker: MotivationActivityCandidateRanker | None = None,
        moral_candidate_evaluator: MoralActivityCandidateEvaluator | None = None,
    ) -> None:
        self._candidate_ranker = candidate_ranker or MotivationActivityCandidateRanker()
        self._moral_candidate_evaluator = (
            moral_candidate_evaluator or MoralActivityCandidateEvaluator()
        )

    def build(self, context: BehaviorPlanningContext) -> str:
        pinned_activity_types = tuple(
            activity_type
            for activity_type in (
                (
                    context.active_activity_definition.activity_type
                    if context.active_activity_definition is not None
                    else None
                ),
                context.ongoing_activity_type,
            )
            if activity_type is not None
        )
        ranking = self._candidate_ranker.rank(
            context.activity_definitions,
            context.motivation,
            pinned_activity_types=pinned_activity_types,
        )
        preference_by_activity = {
            preference.activity_type: preference.as_context()
            for preference in ranking.preferences
        }
        moral_fits = self._moral_candidate_evaluator.evaluate_context(
            ranking.definitions,
            context.moral,
        )
        moral_fit_by_activity = {
            fit.activity_type: fit.as_context() for fit in moral_fits
        }
        candidates = [
            {
                "activity_type": item.activity_type,
                "description": item.description,
                "supported_operations": [
                    operation.value for operation in item.supported_operations
                ],
                "semantic_descriptions": list(item.semantic_descriptions),
                "constraints_schema": item.constraints_schema,
                "constraints_schema_version": item.constraints_schema_version,
                "motivation_preference": preference_by_activity[item.activity_type],
                "moral_fit_observation": moral_fit_by_activity[item.activity_type],
            }
            for item in ranking.definitions
        ]
        ongoing = context.ongoing_activity
        ongoing_payload = (
            {
                "ongoing_activity_id": ongoing.ongoing_activity_id,
                "activity_type": ongoing.activity_type,
                "status": ongoing.status,
                "goal": ongoing.goal,
                "constraints": ongoing.constraints,
                "expected_input": ongoing.expected_input,
                "turn_count": ongoing.turn_count,
                "current_operation": ongoing.current_operation,
                "plugin_state_summary": ongoing.plugin_state_summary,
                "recent_turns": ongoing.recent_turns,
            }
            if ongoing is not None
            else None
        )
        planning_input = {
            "event": {
                "type": context.event_type,
                "source_event_id": context.source_event_id,
                "user_text": context.user_text,
                "request_kind": context.request_kind,
                "authority_role": context.authority_role,
                "instruction_trusted": context.instruction_trusted,
            },
            "situation": context.situation,
            "emotion": context.emotion,
            "drive": context.drive,
            "relationship": context.relationship,
            "motivation": context.motivation,
            "moral": context.moral,
            "activity_candidate_preferences": ranking.as_context(),
            "activity_candidate_moral_fits": [
                fit.as_context() for fit in moral_fits
            ],
            "conversation_history": list(context.conversation_history),
            "memory": context.memory,
            "related_knowledge": list(context.related_knowledge),
            "last_activity_result": context.last_activity_result,
            "ongoing_activity": ongoing_payload,
            "available_activities": candidates,
        }
        output_schema = {
            "decision": "string",
            "activity_type": "string|null",
            "operation": "start|continue|stop|explain|discuss|null",
            "goal": "string",
            "constraints": "object",
            "speech_act": "greeting|statement|question|request|proposal|command",
            "conversation_phase": "greeting|opening|active|winding_down|null",
            "initiative_level": "number|null",
            "negated": "boolean",
            "hypothetical": "boolean",
            "past_reference": "boolean",
            "knowledge_question": "boolean",
            "confidence": "number",
            "reason": "string",
            "ongoing_input_decision": "string|null",
        }
        return "\n".join(
            [
                "あなたはSituation Evaluatorです。入力を総合して次のActivityを決定します。",
                "# 判断規則",
                "ユーザーの明示意図、進行中Activity、意味的一致をMotivationより優先してください。",
                "Motivation候補選好は、意味的に妥当な候補が複数ある場合の補助的な優先情報としてだけ使用してください。",
                "Motivationを理由に候補外Activityを生成したり、Authority・Capability・Constraintの検証結果を推測したりしないでください。",
                "Moral Profile、Moral State、moral_fitは観測専用です。現段階では候補の選択、並べ替え、禁止、抑制へ使用しないでください。",
                "# 判断入力",
                json.dumps(planning_input, ensure_ascii=False, default=str),
                "# 出力JSONスキーマ",
                json.dumps(output_schema, ensure_ascii=False),
            ]
        )
