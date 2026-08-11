from __future__ import annotations

import json
from typing import Any

from app.domain.activities import Activity
from app.domain.response_content_plan import ResponseContentPlan
from cloud_validation import character_response_lab as base
from cloud_validation.character_semantic_response_lab_ui import (
    CHARACTER_SEMANTIC_RESPONSE_LAB_HTML,
)


_INTENSITY_STATES = frozenset({"low", "moderate", "high", "very_high"})
_FAKE_INTENSITY_EVIDENCE = "強度を保った"


class _SemanticFakeRoleModel(base._FakeRoleModel):
    """新Semantic/Realization境界でもfake wiringを通せるLab専用model。"""

    async def generate_character_response(self, activity: Activity) -> str:
        if activity.context.get("llm_role") != "character_language_realizer":
            return await super().generate_character_response(activity)
        semantic_plan = _json_section_from_prompt(
            activity.context.get("plugin_prompt_override"),
            "# Semantic Utterance Plan for Character",
        )
        realization_ids = _realization_ids_from_semantic_plan(semantic_plan)
        state = _primary_state_from_semantic_plan(semantic_plan)
        speech = (
            f"検証用に{_FAKE_INTENSITY_EVIDENCE}応答です。"
            if state in _INTENSITY_STATES
            else "検証用の応答です。"
        )
        return json.dumps(
            {
                "speech": speech,
                "linguistic_performance": {
                    "phrasing": [speech],
                    "emphasis": [],
                    "delivery_tags": ["neutral"],
                },
                "semantic_realizations": realization_ids,
            },
            ensure_ascii=False,
        )

    async def validate_character_response(self, activity: Activity) -> str:
        if activity.context.get("llm_role") != "character_realization_validator":
            return await super().validate_character_response(activity)
        prompt = activity.context.get("plugin_prompt_override")
        semantic_plan = _json_section_from_prompt(prompt, "# Semantic Utterance Plan")
        utterance = _json_section_from_prompt(prompt, "# Character Utterance")
        realization_ids = _validator_realization_ids(utterance)
        speech_value = utterance.get("speech") if isinstance(utterance, dict) else None
        speech = speech_value if isinstance(speech_value, str) else ""
        states_by_id = _states_by_realization_id(semantic_plan)
        realized_checks: list[dict[str, object]] = []
        for realization_id in realization_ids:
            intensity_state = states_by_id.get(realization_id) in _INTENSITY_STATES
            evidence = (
                [_FAKE_INTENSITY_EVIDENCE]
                if intensity_state and _FAKE_INTENSITY_EVIDENCE in speech
                else []
            )
            realized_checks.append(
                {
                    "realization_id": realization_id,
                    "predicate_preserved": True,
                    "state_preserved": True,
                    "state_fidelity": "exact",
                    "certainty_preserved": True,
                    "concept_preserved": True,
                    "intensity_semantics_preserved": True,
                    "presence_only_counterfactual_equivalent": False,
                    "intensity_evidence_spans": evidence,
                }
            )
        return json.dumps(
            {
                "accepted": True,
                "reason": "semantic_realization_consistent",
                "differences": [],
                "semantic_checks": {
                    "required_facets_preserved": True,
                    "predicate_preserved": True,
                    "state_preserved": True,
                    "certainty_preserved": True,
                    "concept_preserved": True,
                    "unsupported_intensity_added": False,
                },
                "realized_proposition_checks": realized_checks,
                "surface_evidence": {
                    "intensity_markers": [],
                },
            },
            ensure_ascii=False,
        )


class _RecordingCharacterModel:
    def __init__(self, delegate: base._CharacterRoleModel, records: list[dict[str, object]]) -> None:
        self._delegate = delegate
        self._records = records

    async def generate_character_response(self, activity: Activity) -> str:
        raw = await self._delegate.generate_character_response(activity)
        self._records.append(_record_call("character", activity, raw))
        return raw


class _RecordingValidatorModel:
    def __init__(self, delegate: base._ValidatorRoleModel, records: list[dict[str, object]]) -> None:
        self._delegate = delegate
        self._records = records

    async def validate_character_response(self, activity: Activity) -> str:
        raw = await self._delegate.validate_character_response(activity)
        self._records.append(_record_call("validator", activity, raw))
        return raw


def _record_call(fallback_role: str, activity: Activity, raw: str) -> dict[str, object]:
    prompt = activity.context.get("plugin_prompt_override")
    actual_role = activity.context.get("llm_role")
    role = (
        str(actual_role).strip()
        if isinstance(actual_role, str) and actual_role.strip()
        else fallback_role
    )
    return {
        "role": role,
        "raw_response": raw,
        "parsed_response": base._parse_json_object(raw),
        "prompt": str(prompt) if isinstance(prompt, str) else None,
        "context_keys": sorted(str(key) for key in activity.context),
        "semantic_boundary": bool(activity.context.get("semantic_boundary")),
    }


def _json_section_from_prompt(prompt: object, marker: str) -> dict[str, object]:
    if not isinstance(prompt, str):
        return {}
    lines = prompt.splitlines()
    try:
        index = lines.index(marker)
    except ValueError:
        return {}
    if index + 1 >= len(lines):
        return {}
    try:
        value = json.loads(lines[index + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _realization_ids_from_semantic_plan(semantic_plan: dict[str, object]) -> list[str]:
    propositions = semantic_plan.get("propositions")
    if not isinstance(propositions, list) or not propositions:
        return []
    first = propositions[0]
    if not isinstance(first, dict):
        return []
    realization_id = first.get("realization_id")
    if not isinstance(realization_id, str) or not realization_id.strip():
        return []
    return [realization_id.strip()]


def _primary_state_from_semantic_plan(semantic_plan: dict[str, object]) -> str | None:
    propositions = semantic_plan.get("propositions")
    if not isinstance(propositions, list) or not propositions:
        return None
    first = propositions[0]
    if not isinstance(first, dict):
        return None
    state = first.get("state")
    return state.strip() if isinstance(state, str) and state.strip() else None


def _validator_realization_ids(utterance: dict[str, object]) -> list[str]:
    ids = utterance.get("semantic_realizations")
    if not isinstance(ids, list):
        return []
    return [item.strip() for item in ids if isinstance(item, str) and item.strip()]


def _states_by_realization_id(semantic_plan: dict[str, object]) -> dict[str, str]:
    propositions = semantic_plan.get("propositions")
    if not isinstance(propositions, list):
        return {}
    result: dict[str, str] = {}
    for item in propositions:
        if not isinstance(item, dict):
            continue
        realization_id = item.get("realization_id")
        state = item.get("state")
        if (
            isinstance(realization_id, str)
            and realization_id.strip()
            and isinstance(state, str)
            and state.strip()
        ):
            result[realization_id.strip()] = state.strip()
    return result


class CharacterSemanticResponseLabService(base.CharacterResponseLabService):
    """既存Labを再利用し、新しい発話生成境界だけ明示的にExportする。"""

    async def analyze(self, request: base.CharacterResponseLabRequest) -> dict[str, object]:
        result = await super().analyze(request)
        context = result.get("response_context")
        response_context = context if isinstance(context, dict) else {}
        memory_value = response_context.get("memory")
        memory = memory_value if isinstance(memory_value, dict) else {}
        model_calls_value = result.get("model_calls")
        model_calls = model_calls_value if isinstance(model_calls_value, list) else []

        # model_callsはattempt履歴を保持する。トップレベル要約は最終採用候補に対応する
        # Character / Validator callを示し、再生成前のreject結果を誤って代表値にしない。
        character_call = _last_call(model_calls, "character_language_realizer")
        validator_call = _last_call(model_calls, "character_realization_validator")
        final_response = result.get("final_response")
        final_data = final_response if isinstance(final_response, dict) else {}

        result["semantic_utterance_plan"] = memory.get("semantic_utterance_plan")
        result["semantic_validation"] = memory.get("semantic_validation")
        result["character_utterance"] = (
            character_call.get("parsed_response") if character_call else None
        )
        result["character_model_boundary"] = (
            _call_boundary(character_call) if character_call else None
        )
        result["realization_validation"] = (
            validator_call.get("parsed_response") if validator_call else None
        )
        result["validator_model_boundary"] = (
            _call_boundary(validator_call) if validator_call else None
        )
        result["linguistic_performance"] = final_data.get("linguistic_performance")
        result["semantic_realizations"] = final_data.get("semantic_realizations")
        result["pipeline_boundaries"] = [
            "semantic_utterance_plan",
            "semantic_validation",
            "character_language_realizer",
            "character_realization_validator",
        ]
        return result

    def _build_role_model(
        self,
        profile: base.CharacterProfile,
        model_name: str,
    ) -> base.ResponseGeneratorRoleAdapter | _SemanticFakeRoleModel | base._UnavailableRoleModel:
        if self._settings.mode == "fake":
            return _SemanticFakeRoleModel()
        return super()._build_role_model(profile, model_name)


def _last_call(
    calls: list[object],
    role: str,
) -> dict[str, Any] | None:
    for item in reversed(calls):
        if isinstance(item, dict) and item.get("role") == role:
            return item
    return None


def _call_boundary(call: dict[str, Any]) -> dict[str, object]:
    return {
        "role": call.get("role"),
        "context_keys": call.get("context_keys", []),
        "semantic_boundary": bool(call.get("semantic_boundary")),
    }


def _fix_preset_reason(key: str, reason: str) -> None:
    preset = base._PRESETS.get(key)
    if not isinstance(preset, dict):
        return
    data = preset.get("data")
    if not isinstance(data, dict):
        return
    meaning = data.get("structured_input_meaning")
    if not isinstance(meaning, dict):
        return
    meaning["reason"] = reason


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


def _set_desire_preset_memory(key: str, primary_desire: str) -> None:
    """全Runtimeを省略するLabでもproductionと同じDesire上流契約を入力する。"""

    preset = base._PRESETS.get(key)
    if not isinstance(preset, dict):
        return
    data = preset.get("data")
    if not isinstance(data, dict):
        return
    memory_value = data.get("memory")
    memory = dict(memory_value) if isinstance(memory_value, dict) else {}
    memory["response_content_plan"] = _desire_content_plan(primary_desire)
    data["memory"] = memory


def _register_extended_presets() -> None:
    """Semantic形の差を検証するExtended Verification専用プリセットを登録する。"""

    base._PRESETS["extended_joy_high"] = base._preset(
        label="拡張E1: 高いJoy",
        user_input="楽しい？",
        target_id="joy",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.78,
                    "amusement": 0.12,
                    "calm": 0.42,
                    "anger": 0.0,
                }
            }
        },
        drive={"curiosity": 0.48, "engagement": 0.56, "energy": 0.8},
    )
    base._PRESETS["extended_sadness_unknown_low"] = base._preset(
        label="拡張E2: Sadness根拠なし",
        user_input="悲しい？",
        target_id="sadness",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.22,
                    "amusement": 0.08,
                    "calm": 0.55,
                    "anger": 0.0,
                }
            }
        },
        drive={"curiosity": 0.52, "engagement": 0.5, "energy": 0.58},
    )
    base._PRESETS["extended_sadness_explicit_unknown"] = base._preset(
        label="拡張E3: Sadness明示Unknown",
        user_input="悲しい？",
        target_id="sadness",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.22,
                    "amusement": 0.08,
                    "calm": 0.55,
                    "anger": 0.0,
                    "sadness": None,
                }
            }
        },
        drive={"curiosity": 0.52, "engagement": 0.5, "energy": 0.58},
    )
    base._PRESETS["extended_current_feeling_mixed"] = base._preset(
        label="拡張E4: 現在の気分・混合",
        user_input="今どんな気分？",
        target_id="current_feeling",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.78,
                    "anger": 0.48,
                    "calm": 0.22,
                    "amusement": 0.02,
                }
            }
        },
        drive={"curiosity": 0.57, "engagement": 0.61, "energy": 0.72},
    )
    base._PRESETS["extended_current_desire_unknown"] = base._preset(
        label="拡張E5: 現在の欲求・根拠なし",
        user_input="何かしたい？",
        target_id="current_desire",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.18,
                    "amusement": 0.06,
                    "calm": 0.58,
                    "anger": 0.0,
                }
            }
        },
        drive={"curiosity": 0.88, "engagement": 0.76, "energy": 0.7},
    )
    base._PRESETS["extended_current_desire_connection"] = base._preset(
        label="拡張E6: 現在の欲求・Connection",
        user_input="何かしたい？",
        target_id="current_desire",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.2,
                    "amusement": 0.08,
                    "calm": 0.6,
                    "anger": 0.0,
                }
            }
        },
        drive={"curiosity": 0.5, "engagement": 0.68, "energy": 0.66},
    )
    _set_desire_preset_memory("extended_current_desire_connection", "connection")


_register_extended_presets()

_fix_preset_reason("joy_low_curiosity_high", "ユーザーは現在の楽しさを直接尋ねている")
_fix_preset_reason("current_feeling_repeat", "ユーザーは現在の気分を直接尋ねている")
_fix_preset_reason("anger_low", "ユーザーは現在怒っているかを直接尋ねている")
_fix_preset_reason("current_desire", "ユーザーは現在何かしたいことがあるかを直接尋ねている")
_fix_preset_reason("extended_joy_high", "ユーザーは現在の楽しさを直接尋ねている")
_fix_preset_reason("extended_sadness_unknown_low", "ユーザーは現在悲しいかを直接尋ねている")
_fix_preset_reason("extended_sadness_explicit_unknown", "ユーザーは現在悲しいかを直接尋ねている")
_fix_preset_reason("extended_current_feeling_mixed", "ユーザーは現在の気分を直接尋ねている")
_fix_preset_reason("extended_current_desire_unknown", "ユーザーは現在何かしたいことがあるかを直接尋ねている")
_fix_preset_reason("extended_current_desire_connection", "ユーザーは現在何かしたいことがあるかを直接尋ねている")
_set_desire_preset_memory("current_desire", "curiosity")

base._RecordingCharacterModel = _RecordingCharacterModel
base._RecordingValidatorModel = _RecordingValidatorModel
base._INDEX_HTML = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML

settings = base.LabSettings.from_env()
service = CharacterSemanticResponseLabService(settings)
app = base.create_app(settings=settings, service=service)

__all__ = [
    "CharacterSemanticResponseLabService",
    "app",
    "service",
    "settings",
]
