from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass

from app.domain.activities import Activity
from app.domain.cognitive_direction import (
    ConversationPhaseSignal,
    InputSpeechAct,
    InterestChange,
    StructuredInputMeaning,
    TargetInterestUpdate,
    ValidatedActionPlan,
)
from app.ports.cognitive_direction import InputMeaningModel, InternalDirectiveModel
from app.runtime.cognitive_direction_services import (
    InputMeaningInterpreter,
    InternalDirectivePlanner,
)
from app.runtime.internal_directive_validator import InternalDirectiveValidator
from app.utils.trace import TraceLogger


class SeparatedSituationEvaluationAdapter:
    """二段LLMの結果を移行中のSituation Evaluator JSON契約へ射影する。"""

    def __init__(
        self,
        input_model: InputMeaningModel,
        directive_model: InternalDirectiveModel,
        *,
        character_profile: object = None,
        input_interpreter: InputMeaningInterpreter | None = None,
        directive_planner: InternalDirectivePlanner | None = None,
        validator: InternalDirectiveValidator | None = None,
    ) -> None:
        self._input_interpreter = input_interpreter or InputMeaningInterpreter(
            input_model
        )
        self._directive_planner = directive_planner or InternalDirectivePlanner(
            directive_model
        )
        self._validator = validator or InternalDirectiveValidator()
        self._character_profile = _profile_context(character_profile)
        self._trace_logger = TraceLogger()

    async def evaluate(self, activity: Activity) -> str | None:
        planning_input = self._extract_planning_input(activity)
        event = planning_input.get("event")
        event_data = event if isinstance(event, dict) else {}
        if str(event_data.get("type") or "user_text") != "user_text":
            return None
        if not str(event_data.get("user_text") or "").strip():
            return None
        meaning = await self._input_interpreter.interpret(activity, planning_input)
        if meaning is None:
            self._trace_logger.warning(
                "input_meaning_interpreter:fallback",
                source_event_id=activity.source_event_id,
            )
            return None
        directive = await self._directive_planner.plan(
            activity,
            meaning,
            planning_input,
            character_profile=self._character_profile,
        )
        if directive is None:
            self._trace_logger.warning(
                "internal_directive_planner:fallback",
                source_event_id=activity.source_event_id,
            )
            return None
        validated = self._validator.validate(
            meaning,
            directive,
            planning_input,
            character_profile=self._character_profile,
        )
        return json.dumps(
            self._legacy_situation_payload(validated),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _extract_planning_input(activity: Activity) -> dict[str, object]:
        prompt = activity.context.get("plugin_prompt_override")
        if isinstance(prompt, str):
            start_marker = "# 判断入力\n"
            end_marker = "\n# 出力JSONスキーマ"
            start = prompt.find(start_marker)
            end = prompt.find(end_marker, start + len(start_marker))
            if start >= 0 and end > start:
                candidate = prompt[start + len(start_marker) : end].strip()
                try:
                    value = json.loads(candidate)
                except json.JSONDecodeError:
                    value = None
                if isinstance(value, dict):
                    return dict(value)
        return {
            "event": {
                "type": "user_text",
                "source_event_id": activity.context.get("event_id"),
                "user_text": activity.context.get("user_input", ""),
            },
            "emotion": activity.context.get("planner_state", {}).get("emotion", {})
            if isinstance(activity.context.get("planner_state"), dict)
            else {},
            "drive": activity.context.get("planner_state", {}).get("drive", {})
            if isinstance(activity.context.get("planner_state"), dict)
            else {},
            "available_activities": [],
        }

    @staticmethod
    def _legacy_situation_payload(plan: ValidatedActionPlan) -> dict[str, object]:
        meaning = plan.meaning
        directive = plan.directive
        activity_intent = directive.activity_intent
        is_conversation = activity_intent is None
        activity_type = (
            "conversation" if is_conversation else activity_intent.activity_type
        )
        operation = "discuss" if is_conversation else activity_intent.operation
        constraints = (
            {"_internal_directive": plan.as_context()}
            if is_conversation
            else dict(activity_intent.constraints)
        )
        return {
            "decision": (
                "conversation" if is_conversation else f"{operation}_activity"
            ),
            "activity_type": activity_type,
            "operation": operation,
            "goal": directive.response_goal,
            "constraints": constraints,
            "speech_act": meaning.input_speech_act.value,
            "conversation_phase": _conversation_phase(meaning),
            "initiative_level": directive.initiative_level,
            "active_interests": _legacy_active_interests(
                directive.target_interest_updates
            ),
            "negated": meaning.negated,
            "hypothetical": meaning.hypothetical,
            "past_reference": meaning.past_reference,
            "knowledge_question": meaning.primary_intent.startswith("ask_knowledge"),
            "confidence": min(meaning.confidence, 0.99),
            "reason": "input_meaning_and_internal_directive_separated",
            "ongoing_input_decision": None,
        }


def _profile_context(profile: object) -> dict[str, object]:
    if profile is None:
        return {
            "name": "ゆら",
            "existence": {
                "existence_type": "AI VTuber",
                "physical_capabilities": ["物理的な身体を持たない"],
                "sensory_capabilities": [
                    "接続された入力や提供された情報から外界を認識する"
                ],
                "experience_boundaries": [
                    "見た・行った・触った等の実体験は根拠がある場合だけ語る"
                ],
            },
        }
    if is_dataclass(profile):
        value = asdict(profile)
        return dict(value) if isinstance(value, dict) else {}
    if isinstance(profile, dict):
        return dict(profile)
    return {}


def _conversation_phase(meaning: StructuredInputMeaning) -> str:
    if meaning.input_speech_act is InputSpeechAct.CLOSING:
        return "winding_down"
    return {
        ConversationPhaseSignal.GREETING: "greeting",
        ConversationPhaseSignal.OPENING: "opening",
        ConversationPhaseSignal.CONTINUE: "active",
        ConversationPhaseSignal.WINDING_DOWN: "winding_down",
    }[meaning.conversation_phase_signal]


def _legacy_active_interests(
    updates: tuple[TargetInterestUpdate, ...],
) -> list[dict[str, object]]:
    values = {
        InterestChange.INCREASE: (0.9, 0.85, 0.1),
        InterestChange.SLIGHTLY_INCREASE: (0.7, 0.7, 0.2),
        InterestChange.UNCHANGED: (0.4, 0.4, 0.5),
        InterestChange.SLIGHTLY_DECREASE: (0.25, 0.25, 0.7),
        InterestChange.DECREASE: (0.1, 0.1, 0.9),
    }
    interests: list[dict[str, object]] = []
    for update in updates:
        interest, gap, satiation = values[update.interest_change]
        if not update.new_knowledge_gaps:
            gap = min(gap, 0.35)
        interests.append(
            {
                "target_type": update.target_type,
                "target_id": update.target_id,
                "interest_intensity": interest,
                "knowledge_gap": gap,
                "satiation": satiation,
                "reason": "; ".join(update.new_knowledge_gaps)
                or update.interest_change.value,
            }
        )
    return interests


