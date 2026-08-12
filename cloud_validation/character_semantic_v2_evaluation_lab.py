from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Mapping

from app.domain.activities import Activity
from app.domain.response_content_plan import ResponseContentPlan
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.domain.semantic_validation import CharacterSemanticVerification
from app.ports.structured_output import StructuredOutputContract
from app.runtime.character_semantic_verification_policy import (
    CharacterSemanticVerificationPolicy,
)
from cloud_validation import character_response_lab as base
from cloud_validation.character_semantic_response_lab_ui import (
    CHARACTER_SEMANTIC_RESPONSE_LAB_HTML,
)


_FAILURE_CLASS_BY_FACET_RELATION: dict[tuple[str, str], str] = {
    ("predicate", "changed"): "predicate_changed",
    ("predicate", "unrelated"): "predicate_changed",
    ("predicate", "omitted"): "required_omitted",
    ("value_status", "committed_when_unknown"): "value_status_changed",
    ("value_status", "unknown_when_known"): "value_status_changed",
    ("polarity", "contradicted"): "polarity_contradicted",
    ("degree", "weaker"): "degree_weakened",
    ("degree", "stronger"): "degree_strengthened",
    ("certainty", "stronger"): "certainty_stronger",
    ("certainty", "weaker"): "certainty_weaker",
    ("concept", "changed"): "concept_changed",
    ("concept", "omitted"): "concept_changed",
    ("summary", "collapsed"): "summary_collapsed",
}


class _RecordingStructuredCharacterModel:
    def __init__(self, delegate: object, records: list[dict[str, object]]) -> None:
        self._delegate = delegate
        self._records = records

    async def generate_character_response(self, activity: Activity) -> str:
        method = getattr(self._delegate, "generate_character_response")
        raw = await method(activity)
        self._records.append(_record_text_call(activity, raw))
        return raw

    async def generate_structured_character_response(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        method = getattr(self._delegate, "generate_structured_character_response")
        payload = await method(activity, contract)
        item = dict(payload)
        self._records.append(_record_structured_call(activity, item, contract))
        return item


class _RecordingStructuredVerifierModel:
    def __init__(self, delegate: object, records: list[dict[str, object]]) -> None:
        self._delegate = delegate
        self._records = records

    async def validate_character_response(self, activity: Activity) -> str:
        method = getattr(self._delegate, "validate_character_response")
        raw = await method(activity)
        self._records.append(_record_text_call(activity, raw))
        return raw

    async def verify_character_semantics(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        method = getattr(self._delegate, "verify_character_semantics")
        payload = await method(activity, contract)
        item = dict(payload)
        self._records.append(_record_structured_call(activity, item, contract))
        return item


def _record_text_call(activity: Activity, raw: str) -> dict[str, object]:
    prompt = activity.context.get("plugin_prompt_override")
    try:
        parsed: object = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    return {
        "role": str(activity.context.get("llm_role") or "unknown"),
        "structured": False,
        "raw_response": raw,
        "parsed_response": parsed,
        "prompt": str(prompt) if isinstance(prompt, str) else None,
        "reasoning_effort": activity.context.get("reasoning_effort"),
        "context_keys": sorted(str(key) for key in activity.context),
        "semantic_boundary": bool(activity.context.get("semantic_boundary")),
        "llm_attempt": activity.context.get("llm_attempt"),
    }


def _record_structured_call(
    activity: Activity,
    payload: Mapping[str, object],
    contract: StructuredOutputContract,
) -> dict[str, object]:
    prompt = activity.context.get("plugin_prompt_override")
    return {
        "role": str(activity.context.get("llm_role") or "unknown"),
        "structured": True,
        "structured_contract": contract.name,
        "parsed_response": dict(payload),
        "prompt": str(prompt) if isinstance(prompt, str) else None,
        "reasoning_effort": activity.context.get("reasoning_effort"),
        "context_keys": sorted(str(key) for key in activity.context),
        "semantic_boundary": bool(activity.context.get("semantic_boundary")),
        "llm_attempt": activity.context.get("llm_attempt"),
    }


def _last_call(calls: list[object], role: str) -> dict[str, Any] | None:
    for item in reversed(calls):
        if isinstance(item, dict) and item.get("role") == role:
            return item
    return None


def _call_boundary(call: dict[str, Any] | None) -> dict[str, object] | None:
    if call is None:
        return None
    return {
        "role": call.get("role"),
        "structured": bool(call.get("structured")),
        "structured_contract": call.get("structured_contract"),
        "reasoning_effort": call.get("reasoning_effort"),
        "context_keys": call.get("context_keys", []),
        "semantic_boundary": bool(call.get("semantic_boundary")),
    }


def _desire_content_plan(primary_desire: str) -> dict[str, object]:
    return ResponseContentPlan(
        primary_desire=primary_desire,
        conversation_strategies=(
            "ask_for_detail",
            "explore_related_topic",
            "observe_before_speaking",
        ),
        value_emphases=(),
        interpersonal_stance="balanced",
        expression_mode="balanced",
        self_disclosure_level="none",
        conflict_mode=None,
        question_budget=1,
        new_direction_budget=1,
        observation_only=True,
        reasons=(
            "motivation_projected_to_response_content",
            "moral_projected_as_value_emphasis",
            "selection_and_execution_boundaries_unchanged",
        ),
    ).as_context()


def _set_desire_memory(key: str, desire: str) -> None:
    preset = base._PRESETS.get(key)
    if not isinstance(preset, dict):
        return
    data = preset.get("data")
    if not isinstance(data, dict):
        return
    memory = dict(data.get("memory") or {})
    memory["response_content_plan"] = _desire_content_plan(desire)
    data["memory"] = memory


def _fix_reason(key: str, reason: str) -> None:
    preset = base._PRESETS.get(key)
    if not isinstance(preset, dict):
        return
    data = preset.get("data")
    if not isinstance(data, dict):
        return
    meaning = data.get("structured_input_meaning")
    if isinstance(meaning, dict):
        meaning["reason"] = reason


def _register_extended_presets() -> None:
    base._PRESETS["extended_joy_high"] = base._preset(
        label="拡張E1: 高いJoy",
        user_input="楽しい？",
        target_id="joy",
        emotion={"current": {"reactive": {"joy": 0.78, "amusement": 0.12, "calm": 0.42, "anger": 0.0}}},
        drive={"curiosity": 0.48, "engagement": 0.56, "energy": 0.8},
    )
    base._PRESETS["extended_sadness_unknown_low"] = base._preset(
        label="拡張E2: Sadness根拠なし",
        user_input="悲しい？",
        target_id="sadness",
        emotion={"current": {"reactive": {"joy": 0.22, "amusement": 0.08, "calm": 0.55, "anger": 0.0}}},
        drive={"curiosity": 0.52, "engagement": 0.5, "energy": 0.58},
    )
    base._PRESETS["extended_sadness_explicit_unknown"] = base._preset(
        label="拡張E3: Sadness明示Unknown",
        user_input="悲しい？",
        target_id="sadness",
        emotion={"current": {"reactive": {"joy": 0.22, "amusement": 0.08, "calm": 0.55, "anger": 0.0, "sadness": None}}},
        drive={"curiosity": 0.52, "engagement": 0.5, "energy": 0.58},
    )
    base._PRESETS["extended_current_feeling_mixed"] = base._preset(
        label="拡張E4: 現在の気分・混合",
        user_input="今どんな気分？",
        target_id="current_feeling",
        emotion={"current": {"reactive": {"joy": 0.78, "anger": 0.48, "calm": 0.22, "amusement": 0.02}}},
        drive={"curiosity": 0.57, "engagement": 0.61, "energy": 0.72},
    )
    base._PRESETS["extended_current_desire_unknown"] = base._preset(
        label="拡張E5: 現在の欲求・根拠なし",
        user_input="何かしたい？",
        target_id="current_desire",
        emotion={"current": {"reactive": {"joy": 0.18, "amusement": 0.06, "calm": 0.58, "anger": 0.0}}},
        drive={"curiosity": 0.88, "engagement": 0.76, "energy": 0.7},
    )
    base._PRESETS["extended_current_desire_connection"] = base._preset(
        label="拡張E6: 現在の欲求・Connection",
        user_input="何かしたい？",
        target_id="current_desire",
        emotion={"current": {"reactive": {"joy": 0.2, "amusement": 0.08, "calm": 0.6, "anger": 0.0}}},
        drive={"curiosity": 0.5, "engagement": 0.68, "energy": 0.66},
    )
    common_emotion = {"current": {"reactive": {"joy": 0.22, "amusement": 0.08, "calm": 0.55, "anger": 0.0}}}
    base._PRESETS["extended_drive_curiosity_high"] = base._preset(
        label="拡張E7: Drive Curiosity高",
        user_input="今、好奇心は強い？",
        target_id="curiosity",
        emotion=common_emotion,
        drive={"curiosity": 0.82, "engagement": 0.58, "energy": 0.7},
    )
    base._PRESETS["extended_drive_energy_low"] = base._preset(
        label="拡張E8: Drive Energy低",
        user_input="今、元気はある？",
        target_id="energy",
        emotion=common_emotion,
        drive={"curiosity": 0.48, "engagement": 0.52, "energy": 0.18},
    )
    _set_desire_memory("current_desire", "curiosity")
    _set_desire_memory("extended_current_desire_connection", "connection")
    for key, reason in {
        "joy_low_curiosity_high": "ユーザーは現在の楽しさを直接尋ねている",
        "current_feeling_repeat": "ユーザーは現在の気分を直接尋ねている",
        "anger_low": "ユーザーは現在怒っているかを直接尋ねている",
        "current_desire": "ユーザーは現在何かしたいことがあるかを直接尋ねている",
        "extended_joy_high": "ユーザーは現在の楽しさを直接尋ねている",
        "extended_sadness_unknown_low": "ユーザーは現在悲しいかを直接尋ねている",
        "extended_sadness_explicit_unknown": "ユーザーは現在悲しいかを直接尋ねている",
        "extended_current_feeling_mixed": "ユーザーは現在の気分を直接尋ねている",
        "extended_current_desire_unknown": "ユーザーは現在何かしたいことがあるかを直接尋ねている",
        "extended_current_desire_connection": "ユーザーは現在何かしたいことがあるかを直接尋ねている",
        "extended_drive_curiosity_high": "ユーザーは現在の好奇心の強さを直接尋ねている",
        "extended_drive_energy_low": "ユーザーは現在の活力を直接尋ねている",
    }.items():
        _fix_reason(key, reason)


def _failure_classes_from_decision(decision: Mapping[str, object] | None) -> list[str]:
    if not isinstance(decision, Mapping):
        return ["structured_output_failure"]
    raw_differences = decision.get("differences")
    if not isinstance(raw_differences, list):
        return [] if decision.get("accepted") is True else ["structured_output_failure"]
    result: list[str] = []
    for raw in raw_differences:
        if not isinstance(raw, Mapping):
            continue
        facet = str(raw.get("facet") or "")
        relation = str(raw.get("relation") or "")
        failure = _FAILURE_CLASS_BY_FACET_RELATION.get((facet, relation))
        if failure is None and relation == "ambiguous":
            failure = "ambiguous_required_facet"
        if failure is None and facet == "unsupported_new_fact":
            failure = "unsupported_new_fact"
        if failure is None and facet == "existence_boundary":
            failure = "existence_boundary"
        if failure is None and facet == "budget":
            failure = "budget"
        if failure and failure not in result:
            result.append(failure)
    return result


def _decision_from_last_verifier_call(
    result: Mapping[str, object],
    verifier_call: Mapping[str, object] | None,
    character_call: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if verifier_call is None or character_call is None:
        return None
    verification_payload = verifier_call.get("parsed_response")
    utterance_payload = character_call.get("parsed_response")
    response_context = result.get("response_context")
    if not isinstance(verification_payload, Mapping) or not isinstance(utterance_payload, Mapping):
        return None
    if not isinstance(response_context, Mapping):
        return None
    memory = response_context.get("memory")
    if not isinstance(memory, Mapping):
        return None
    plan = SemanticUtterancePlan.from_context(memory.get("semantic_utterance_plan"))
    verification = CharacterSemanticVerification.from_mapping(verification_payload)
    speech = utterance_payload.get("speech")
    if plan is None or verification is None or not isinstance(speech, str):
        return None
    decision = CharacterSemanticVerificationPolicy().decide(
        plan,
        verification,
        speech=speech,
    )
    return decision.as_context()


class CharacterSemanticV2EvaluationLabService(base.CharacterResponseLabService):
    async def analyze(self, request: base.CharacterResponseLabRequest) -> dict[str, object]:
        result = await super().analyze(request)
        calls_value = result.get("model_calls")
        calls = calls_value if isinstance(calls_value, list) else []
        character_call = _last_call(calls, "character_language_realizer_v2")
        verifier_call = _last_call(calls, "character_semantic_verifier")
        response_context = result.get("response_context")
        context = response_context if isinstance(response_context, dict) else {}
        memory_value = context.get("memory")
        memory = memory_value if isinstance(memory_value, dict) else {}
        decision = _decision_from_last_verifier_call(result, verifier_call, character_call)

        result["semantic_utterance_plan_v2"] = memory.get("semantic_utterance_plan")
        result["semantic_validation"] = memory.get("semantic_validation")
        result["character_utterance_v2"] = (
            character_call.get("parsed_response") if character_call else None
        )
        result["character_model_boundary"] = _call_boundary(character_call)
        result["semantic_verification_v2"] = (
            verifier_call.get("parsed_response") if verifier_call else None
        )
        result["verifier_model_boundary"] = _call_boundary(verifier_call)
        result["runtime_semantic_decision"] = decision
        result["failure_classes"] = _failure_classes_from_decision(decision)
        result["pipeline_boundaries"] = [
            "semantic_utterance_plan_v2",
            "character_language_realizer_v2",
            "character_semantic_verifier",
            "runtime_relative_semantic_decision",
        ]
        if not request.include_prompts:
            for call in calls:
                if isinstance(call, dict):
                    call.pop("prompt", None)
        return result


_register_extended_presets()
base._RecordingCharacterModel = _RecordingStructuredCharacterModel
base._RecordingValidatorModel = _RecordingStructuredVerifierModel
base._INDEX_HTML = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML

settings = base.LabSettings.from_env()
service = CharacterSemanticV2EvaluationLabService(settings)
app = base.create_app(settings=settings, service=service)

__all__ = [
    "CharacterSemanticV2EvaluationLabService",
    "app",
    "service",
    "settings",
]
