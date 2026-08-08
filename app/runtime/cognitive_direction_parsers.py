from __future__ import annotations

import json
from typing import Any

from app.domain.body_instruction import BodyInstruction
from app.domain.cognitive_direction import (
    ActivityIntent,
    ConversationPhaseSignal,
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    InterestChange,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
    TargetInterestUpdate,
)


class InputMeaningJsonParser:
    _TARGET_REQUIRED_SPEECH_ACTS = {
        InputSpeechAct.QUESTION,
        InputSpeechAct.REQUEST,
        InputSpeechAct.COMMAND,
    }
    _REQUIRED = {
        "input_speech_act",
        "primary_intent",
        "expected_response",
        "target",
        "entities",
        "references",
        "negated",
        "hypothetical",
        "past_reference",
        "conversation_phase_signal",
        "confidence",
        "reason",
    }

    def parse(self, raw: str, *, source_text: str) -> StructuredInputMeaning | None:
        payload = _json_object(raw)
        if payload is None or not self._REQUIRED.issubset(payload):
            return None
        try:
            speech_act = InputSpeechAct(str(payload["input_speech_act"]))
            expected_response = ExpectedResponse(str(payload["expected_response"]))
            phase = ConversationPhaseSignal(
                str(payload["conversation_phase_signal"])
            )
        except ValueError:
            return None
        target_value = payload["target"]
        if target_value is None:
            target = None
        elif isinstance(target_value, dict):
            target_type = target_value.get("type")
            target_id = target_value.get("id")
            if not isinstance(target_type, str) or not isinstance(target_id, str):
                return None
            try:
                target = InputTarget(target_type, target_id)
            except ValueError:
                return None
        else:
            return None
        if target is None and speech_act in self._TARGET_REQUIRED_SPEECH_ACTS:
            return None
        body_instruction_value = payload.get("body_instruction")
        body_instruction = BodyInstruction.from_context(body_instruction_value)
        if body_instruction_value is not None and body_instruction is None:
            return None
        primary_intent = payload["primary_intent"]
        reason = payload["reason"]
        entities = _object_tuple(payload["entities"])
        references = _object_tuple(payload["references"])
        information = _string_tuple(payload.get("information_provided", []))
        flags = ("negated", "hypothetical", "past_reference")
        confidence = payload["confidence"]
        if (
            not isinstance(primary_intent, str)
            or not isinstance(reason, str)
            or entities is None
            or references is None
            or information is None
        ):
            return None
        if not all(isinstance(payload[name], bool) for name in flags):
            return None
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0.0 <= float(confidence) <= 1.0
        ):
            return None
        try:
            return StructuredInputMeaning(
                input_speech_act=speech_act,
                primary_intent=primary_intent,
                expected_response=expected_response,
                target=target,
                body_instruction=body_instruction,
                entities=entities,
                references=references,
                information_provided=information,
                negated=bool(payload["negated"]),
                hypothetical=bool(payload["hypothetical"]),
                past_reference=bool(payload["past_reference"]),
                conversation_phase_signal=phase,
                confidence=float(confidence),
                reason=reason,
                source_text=source_text,
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def has_missing_semantic_target(cls, raw: str) -> bool:
        """typed speech actだけを使ってtarget欠落契約違反を識別する。"""

        payload = _json_object(raw)
        if payload is None or payload.get("target") is not None:
            return False
        try:
            speech_act = InputSpeechAct(str(payload.get("input_speech_act")))
        except ValueError:
            return False
        return speech_act in cls._TARGET_REQUIRED_SPEECH_ACTS


class InternalDirectiveJsonParser:
    _REQUIRED = {
        "response_mode",
        "response_goal",
        "activity_intent",
        "initiative_level",
        "question_budget",
        "new_direction_budget",
        "self_disclosure_level",
        "content_requirements",
        "forbidden_claims",
        "target_interest_updates",
        "state_update_proposals",
        "reason",
    }

    def parse(self, raw: str) -> InternalDirective | None:
        payload = _json_object(raw)
        if payload is None or not self._REQUIRED.issubset(payload):
            return None
        try:
            response_mode = ResponseMode(str(payload["response_mode"]))
        except ValueError:
            return None
        activity_intent = self._activity_intent(payload["activity_intent"])
        if payload["activity_intent"] is not None and activity_intent is None:
            return None
        response_goal = payload["response_goal"]
        reason = payload["reason"]
        initiative_level = payload["initiative_level"]
        question_budget = payload["question_budget"]
        new_direction_budget = payload["new_direction_budget"]
        self_disclosure_level = payload["self_disclosure_level"]
        content_requirements = _string_tuple(payload["content_requirements"])
        forbidden_claims = _string_tuple(payload["forbidden_claims"])
        proposals = _object_tuple(payload["state_update_proposals"])
        updates = self._target_interest_updates(payload["target_interest_updates"])
        numeric_values = (initiative_level, self_disclosure_level)
        integer_values = (question_budget, new_direction_budget)
        if (
            not isinstance(response_goal, str)
            or not isinstance(reason, str)
            or any(
                not isinstance(value, (int, float)) or isinstance(value, bool)
                for value in numeric_values
            )
            or any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in integer_values
            )
            or content_requirements is None
            or forbidden_claims is None
            or proposals is None
            or updates is None
        ):
            return None
        try:
            return InternalDirective(
                response_mode=response_mode,
                response_goal=response_goal,
                activity_intent=activity_intent,
                initiative_level=float(initiative_level),
                question_budget=question_budget,
                new_direction_budget=new_direction_budget,
                self_disclosure_level=float(self_disclosure_level),
                content_requirements=content_requirements,
                forbidden_claims=forbidden_claims,
                target_interest_updates=updates,
                state_update_proposals=proposals,
                reason=reason,
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _activity_intent(value: object) -> ActivityIntent | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            return None
        activity_type = value.get("activity_type")
        operation = value.get("operation")
        constraints = value.get("constraints", {})
        if (
            not isinstance(activity_type, str)
            or not isinstance(operation, str)
            or not isinstance(constraints, dict)
        ):
            return None
        try:
            return ActivityIntent(activity_type, operation, dict(constraints))
        except ValueError:
            return None

    @staticmethod
    def _target_interest_updates(
        value: object,
    ) -> tuple[TargetInterestUpdate, ...] | None:
        if not isinstance(value, list):
            return None
        updates: list[TargetInterestUpdate] = []
        for item in value:
            if not isinstance(item, dict):
                return None
            target_type = item.get("target_type")
            target_id = item.get("target_id")
            interest_change = item.get("interest_change")
            if (
                not isinstance(target_type, str)
                or not isinstance(target_id, str)
                or not isinstance(interest_change, str)
            ):
                return None
            try:
                update = TargetInterestUpdate(
                    target_type=target_type,
                    target_id=target_id,
                    interest_change=InterestChange(interest_change),
                    resolved_knowledge_gaps=_required_string_tuple(
                        item.get("resolved_knowledge_gaps", [])
                    ),
                    new_knowledge_gaps=_required_string_tuple(
                        item.get("new_knowledge_gaps", [])
                    ),
                )
            except (KeyError, TypeError, ValueError):
                return None
            updates.append(update)
        return tuple(updates)


def _json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            return None
        text = "\n".join(lines[1:-1]).strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return dict(value) if isinstance(value, dict) else None


def _object_tuple(value: object) -> tuple[dict[str, object], ...] | None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return None
    return tuple(dict(item) for item in value)


def _string_tuple(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return tuple(item for item in value)


def _required_string_tuple(value: object) -> tuple[str, ...]:
    result = _string_tuple(value)
    if result is None:
        raise TypeError("expected array[string]")
    return result
