from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter
from typing import Mapping
from uuid import uuid4

from pydantic import BaseModel, Field

from app.adapters.prompt.character_language_realizer_v2_prompt_builder import (
    CharacterLanguageRealizerV2PromptBuilder,
)
from app.adapters.prompt.character_semantic_verifier_prompt_builder import (
    CharacterSemanticVerifierPromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
)
from app.domain.cognitive_direction import ValidatedActionPlan
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.ports.structured_output import StructuredOutputContract
from app.runtime.character_language_realizer_v2 import CharacterLanguageRealizerV2
from app.runtime.character_semantic_verifier import CharacterSemanticVerifier
from cloud_validation import character_response_lab as base


class ModelMatrixRequest(BaseModel):
    preset_keys: list[str] = Field(default_factory=list)
    include_prompts: bool = False
    include_diagnostic_upper: bool = True
    character_reasoning: str = "none"
    verifier_reasoning: str = "low"


@dataclass(frozen=True, slots=True)
class ModelMatrixSettings:
    baseline_character_model: str
    baseline_verifier_model: str
    diagnostic_model: str

    @classmethod
    def from_env(cls, base_settings: base.LabSettings) -> "ModelMatrixSettings":
        return cls(
            baseline_character_model=base_settings.model,
            baseline_verifier_model=base_settings.validator_model,
            diagnostic_model=os.getenv(
                "YURA_CHARACTER_RESPONSE_LAB_DIAGNOSTIC_MODEL",
                "",
            ).strip(),
        )


class V2FakeRoleModel:
    """v2 wiring専用。自然言語意味分類を行わずclosed Plan IDをechoする。"""

    async def generate_response(self, activity: Activity) -> str:
        del activity
        return "{}"

    async def generate_character_response(self, activity: Activity) -> str:
        del activity
        return "{}"

    async def validate_character_response(self, activity: Activity) -> str:
        del activity
        return "{}"

    async def generate_structured_character_response(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        assert contract.name == "character_utterance_v2"
        plan = _json_section(activity.context.get("plugin_prompt_override"), "# Semantic Plan v2")
        propositions = plan.get("propositions") if isinstance(plan, dict) else None
        selected: list[dict[str, object]] = []
        if isinstance(propositions, list):
            for item in propositions:
                if not isinstance(item, dict):
                    continue
                if item.get("realization_policy") != "required":
                    continue
                proposition_id = item.get("proposition_id")
                if isinstance(proposition_id, str) and proposition_id:
                    selected.append(
                        {
                            "proposition_id": proposition_id,
                            "evidence_spans": [f"検証:{proposition_id}"],
                        }
                    )
        speech = " / ".join(
            span
            for item in selected
            for span in item["evidence_spans"]
            if isinstance(span, str)
        ) or "検証用応答"
        return {
            "speech": speech,
            "linguistic_performance": {
                "phrasing": [speech],
                "emphasis": [],
                "delivery_tags": ["neutral"],
            },
            "realizations": selected,
        }

    async def verify_character_semantics(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        assert contract.name == "character_semantic_verification_v2"
        plan = _json_section(activity.context.get("plugin_prompt_override"), "# Semantic Plan")
        propositions = plan.get("propositions") if isinstance(plan, dict) else None
        checks: list[dict[str, object]] = []
        if isinstance(propositions, list):
            for item in propositions:
                if not isinstance(item, dict):
                    continue
                proposition_id = item.get("proposition_id")
                if not isinstance(proposition_id, str) or not proposition_id:
                    continue
                required = item.get("realization_policy") == "required"
                if not required:
                    checks.append(
                        {
                            "proposition_id": proposition_id,
                            "realized": False,
                            "predicate_relation": "omitted",
                            "value_status_relation": "not_applicable",
                            "polarity_relation": "not_applicable",
                            "degree_relation": "not_applicable",
                            "certainty_relation": "not_applicable",
                            "concept_relation": "not_applicable",
                            "summary_relation": "not_applicable",
                            "evidence_spans": [],
                        }
                    )
                    continue
                value = item.get("value")
                value_map = value if isinstance(value, dict) else {}
                checks.append(
                    {
                        "proposition_id": proposition_id,
                        "realized": True,
                        "predicate_relation": "preserved",
                        "value_status_relation": "preserved",
                        "polarity_relation": (
                            "preserved" if value_map.get("polarity") is not None else "not_applicable"
                        ),
                        "degree_relation": (
                            "preserved" if value_map.get("degree") is not None else "not_applicable"
                        ),
                        "certainty_relation": "preserved",
                        "concept_relation": (
                            "preserved" if item.get("concept") is not None else "not_applicable"
                        ),
                        "summary_relation": (
                            "preserved" if item.get("summary_mode") == "overview" else "not_applicable"
                        ),
                        "evidence_spans": [f"検証:{proposition_id}"],
                    }
                )
        return {
            "propositions": checks,
            "required_content_preserved": True,
            "forbidden_additions_absent": True,
            "unsupported_new_fact_absent": True,
            "existence_boundary_preserved": True,
            "budget_preserved": True,
            "global_evidence_spans": [],
        }


def _json_section(prompt: object, marker: str) -> dict[str, object]:
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
    return dict(value) if isinstance(value, dict) else {}


class CharacterSemanticV2ModelMatrixService:
    def __init__(
        self,
        base_settings: base.LabSettings,
        *,
        settings: ModelMatrixSettings | None = None,
    ) -> None:
        self._base_settings = base_settings
        self._settings = settings or ModelMatrixSettings.from_env(base_settings)
        self._model_factory = base.CharacterResponseLabService(base_settings)

    async def analyze(self, request: ModelMatrixRequest) -> dict[str, object]:
        preset_keys = request.preset_keys or list(base._PRESETS)
        unknown = [key for key in preset_keys if key not in base._PRESETS]
        if unknown:
            raise ValueError(f"unknown preset keys: {unknown}")

        character_models = [self._settings.baseline_character_model]
        verifier_models = [self._settings.baseline_verifier_model]
        if request.include_diagnostic_upper and self._settings.diagnostic_model:
            if self._settings.diagnostic_model not in character_models:
                character_models.append(self._settings.diagnostic_model)
            if self._settings.diagnostic_model not in verifier_models:
                verifier_models.append(self._settings.diagnostic_model)

        started = perf_counter()
        cases: list[dict[str, object]] = []
        aggregate: dict[str, int] = {}
        for preset_key in preset_keys:
            preset = base._PRESETS[preset_key]
            data = preset.get("data") if isinstance(preset, dict) else None
            if not isinstance(data, dict):
                continue
            request_data = deepcopy(data)
            request_data["include_prompts"] = request.include_prompts
            lab_request = base.CharacterResponseLabRequest(**request_data)
            case = await self._analyze_case(
                preset_key,
                str(preset.get("label") or preset_key),
                lab_request,
                character_models=character_models,
                verifier_models=verifier_models,
                character_reasoning=request.character_reasoning,
                verifier_reasoning=request.verifier_reasoning,
                include_prompts=request.include_prompts,
            )
            cases.append(case)
            for item in case.get("matrix", []):
                if not isinstance(item, dict):
                    continue
                for failure in item.get("failure_classes", []):
                    if isinstance(failure, str):
                        aggregate[failure] = aggregate.get(failure, 0) + 1

        return {
            "mode": self._base_settings.mode,
            "baseline": {
                "character_model": self._settings.baseline_character_model,
                "character_reasoning": request.character_reasoning,
                "verifier_model": self._settings.baseline_verifier_model,
                "verifier_reasoning": request.verifier_reasoning,
            },
            "diagnostic_model": self._settings.diagnostic_model or None,
            "case_count": len(cases),
            "character_models": character_models,
            "verifier_models": verifier_models,
            "character_generation_count": len(cases) * len(character_models),
            "verification_count": len(cases) * len(character_models) * len(verifier_models),
            "failure_class_counts": aggregate,
            "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
            "cases": cases,
        }

    async def _analyze_case(
        self,
        preset_key: str,
        label: str,
        request: base.CharacterResponseLabRequest,
        *,
        character_models: list[str],
        verifier_models: list[str],
        character_reasoning: str,
        verifier_reasoning: str,
        include_prompts: bool,
    ) -> dict[str, object]:
        profile, activity, context, plan = self._prepare(request)
        character_candidates: dict[str, object] = {}
        matrix: list[dict[str, object]] = []

        for character_model_name in character_models:
            character_delegate = self._role_model(profile, character_model_name)
            realizer = CharacterLanguageRealizerV2(
                character_delegate,  # type: ignore[arg-type]
                CharacterLanguageRealizerV2PromptBuilder(),
                character_profile=profile,
                reasoning_effort=character_reasoning,
            )
            started = perf_counter()
            try:
                utterance = await realizer.generate_utterance(activity, context)
            except Exception as error:
                character_candidates[character_model_name] = {
                    "ok": False,
                    "error": type(error).__name__,
                    "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
                }
                continue
            character_candidates[character_model_name] = {
                "ok": True,
                "speech": utterance.speech,
                "realizations": [item.as_context() for item in utterance.realizations],
                "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
            }

            for verifier_model_name in verifier_models:
                verifier_delegate = self._role_model(profile, verifier_model_name)
                verifier = CharacterSemanticVerifier(
                    verifier_delegate,  # type: ignore[arg-type]
                    CharacterSemanticVerifierPromptBuilder(),
                    reasoning_effort=verifier_reasoning,
                )
                verify_started = perf_counter()
                verifier_result = await verifier.verify(
                    activity,
                    context,
                    utterance,
                    plan,
                    existence_boundaries=profile.existence.behavior_policies(),
                )
                decision = verifier_result.decision.as_context()
                failure_classes = _failure_classes(decision)
                matrix.append(
                    {
                        "character_model": character_model_name,
                        "verifier_model": verifier_model_name,
                        "character_reasoning": character_reasoning,
                        "verifier_reasoning": verifier_reasoning,
                        "speech": utterance.speech,
                        "verification": (
                            verifier_result.verification.as_context()
                            if verifier_result.verification is not None
                            else None
                        ),
                        "decision": decision,
                        "failure_classes": failure_classes,
                        "verification_elapsed_ms": round(
                            (perf_counter() - verify_started) * 1000.0,
                            3,
                        ),
                    }
                )

        return {
            "preset_key": preset_key,
            "label": label,
            "semantic_utterance_plan_v2": plan.as_context(),
            "character_candidates": character_candidates,
            "matrix": matrix,
        }

    def _prepare(
        self,
        request: base.CharacterResponseLabRequest,
    ) -> tuple[base.CharacterProfile, Activity, object, SemanticUtterancePlan]:
        profile = self._model_factory._character_profile(request.character_profile)
        meaning = self._model_factory._meaning(request.structured_input_meaning)
        directive = self._model_factory._directive(request.internal_directive)
        envelope = ValidatedActionPlan(
            meaning=meaning,
            directive=directive,
            character_profile=dict(request.character_profile),
            existence_boundaries=profile.existence.behavior_policies(),
        ).as_context()
        source_event_id = f"character-semantic-v2-matrix-{uuid4()}"
        constraints = dict(request.response_constraints)
        constraints["_internal_directive"] = envelope
        result = ActivityExecutionResult(
            activity_type="conversation",
            operation="discuss",
            status=ActivityExecutionStatus.WAITING_INPUT,
            payload={"summary": "Character Semantic v2 model matrix"},
            constraints=constraints,
            source_event_id=source_event_id,
        )
        behavior_plan = {
            "speech_act": meaning.input_speech_act.value,
            "conversation_phase": self._model_factory._conversation_phase(meaning),
            "initiative_level": directive.initiative_level,
        }
        activity = Activity(
            activity_type=ActivityType.CONVERSATION_WITH_USER,
            goal=directive.response_goal,
            context={
                "emotion": deepcopy(request.emotion),
                "event_payload": {
                    "text": request.user_input,
                    "activity_execution_result": result,
                    "behavior_plan": behavior_plan,
                    "autonomous_situation_context": {
                        "drive_state": dict(request.drive),
                        "recent_speech_summary": request.recent_speech_summary,
                        "recent_topic_summary": request.recent_topic_summary,
                    },
                    "memory": deepcopy(request.memory),
                    "related_knowledge": deepcopy(request.related_knowledge),
                    "conversation_history": deepcopy(request.recent_conversation),
                },
                "cloud_validation": True,
            },
            source_event_id=source_event_id,
        )
        context = base.ResponseContextBuilder().build(activity)
        plan = SemanticUtterancePlan.from_context(
            context.memory.get("semantic_utterance_plan")
        )
        if plan is None or not plan.propositions:
            raise ValueError("Semantic Plan v2 could not be prepared")
        return profile, activity, context, plan

    def _role_model(self, profile: base.CharacterProfile, model_name: str) -> object:
        if self._base_settings.mode == "fake":
            return V2FakeRoleModel()
        return self._model_factory._build_role_model(profile, model_name)


def _failure_classes(decision: Mapping[str, object]) -> list[str]:
    raw_differences = decision.get("differences")
    if not isinstance(raw_differences, list):
        return [] if decision.get("accepted") is True else ["structured_output_failure"]
    classes: list[str] = []
    for raw in raw_differences:
        if not isinstance(raw, Mapping):
            continue
        facet = str(raw.get("facet") or "")
        relation = str(raw.get("relation") or "")
        key = (facet, relation)
        value = {
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
        }.get(key)
        if value is None and relation == "ambiguous":
            value = "ambiguous_required_facet"
        if value is None and facet == "unsupported_new_fact":
            value = "unsupported_new_fact"
        if value is None and facet == "existence_boundary":
            value = "existence_boundary"
        if value is None and facet == "budget":
            value = "budget"
        if value and value not in classes:
            classes.append(value)
    return classes
