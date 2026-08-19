from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.adapters.llm.character_language import (
    CHARACTER_LANGUAGE_PROVIDER_FORMAT_NAME,
    character_language_openai_role_config,
)
from app.adapters.llm.openai_responses import OpenAIResponsesAdapter, OpenAIResponsesRoleConfig
from app.domain.character.contracts import CharacterLanguageProfile
from app.domain.character_language import (
    MAX_PRIOR_REALIZATIONS,
    CharacterLanguageAuthority,
    CharacterLanguageContextSnapshot,
    CharacterLanguagePolicy,
    CharacterLanguagePriorRealizationView,
    CharacterLanguageRealizer,
    CharacterUtterance,
    prior_realization_from_utterance,
)
from app.domain.llm import LLMInterruptibility, LLMPriority
from app.domain.speech_semantics import SpeechSemanticPlan
from app.usecases.ports.llm import LLMRolePort
from cloud_validation.v2_character_language_diagnostics import (
    DiagnosticCharacterLanguageLabService,
)
from cloud_validation.v2_character_language_lab import (
    LAB_BRANCH,
    CharacterLanguageLabMode,
    CharacterLanguageLabRequest,
    CharacterLanguageLabStatus,
    _RecordingPort,
    _SCENARIOS,
    _StaticCharacterLiveState,
    _character_source,
    _committed_plan,
    _execution_policy,
    _profile_dict,
    _semantic_role_configs,
)


class StrictSamePlanCharacterLanguageLabService(DiagnosticCharacterLanguageLabService):
    """1 batch=1 Planで#330 bounded prior awarenessを実測する#434 engine。"""

    async def run(self, request: CharacterLanguageLabRequest) -> dict[str, object]:
        scenario = _SCENARIOS.get(request.scenario_id)
        if scenario is None:
            raise ValueError("unknown scenario_id")
        profile, source = _character_source(self._settings, request.mode)
        if profile is None:
            return {
                "ok": False,
                "status": CharacterLanguageLabStatus.BLOCKED_UPSTREAM_CHARACTER_DEFINITION.value,
                "mode": request.mode.value,
                "evidence_class": "not_eligible",
                "integrated_evidence_eligible": False,
                "character_source": source,
                "runs": [],
            }

        recorder = _RecordingPort(self._role_port(request))
        plan = await _committed_plan(scenario)
        runs: list[dict[str, object]] = []
        priors: tuple[CharacterLanguagePriorRealizationView, ...] = ()

        for repetition_index in range(request.repetitions):
            run_value, utterance = await self._run_once_same_plan(
                request,
                plan,
                profile,
                source,
                recorder,
                priors,
                repetition_index,
            )
            runs.append(run_value)
            if utterance is not None:
                prior = prior_realization_from_utterance(utterance, ())
                priors = _append_unique_prior(priors, prior)

        return {
            "ok": all(bool(item.get("ok")) for item in runs),
            "status": CharacterLanguageLabStatus.COMPLETED.value,
            "mode": request.mode.value,
            "evidence_class": (
                "integrated"
                if request.mode is CharacterLanguageLabMode.INTEGRATED
                else "isolation_only"
            ),
            "integrated_evidence_eligible": (
                request.mode is CharacterLanguageLabMode.INTEGRATED
            ),
            "scenario": {"id": scenario.scenario_id, "label": scenario.label},
            "character_source": source,
            "model_policy": {
                "character": {
                    "provider_model": request.character_model,
                    "model_class": request.character_model_class.value,
                    "reasoning_effort": request.character_reasoning_effort.value,
                    "provider_format": CHARACTER_LANGUAGE_PROVIDER_FORMAT_NAME,
                },
                "semantic": {
                    "enabled": request.run_semantic_verification,
                    "provider_model": request.semantic_model,
                    "model_class": request.semantic_model_class.value,
                    "reasoning_effort": request.semantic_reasoning_effort.value,
                },
            },
            "variation_batch": {
                "semantic_plan_id": plan.plan_id,
                "repetitions": request.repetitions,
                "strict_same_plan": True,
                "max_prior_realizations": MAX_PRIOR_REALIZATIONS,
            },
            "runs": runs,
            "provider_metrics": recorder.metrics(),
            "branch": LAB_BRANCH,
            "git_head": self._settings.git_head,
        }

    def _role_port(self, request: CharacterLanguageLabRequest) -> LLMRolePort:
        if self._injected_port is not None:
            return self._injected_port
        if not self._settings.provider_configured:
            raise ValueError("OPENAI_API_KEYが設定されていません")
        character_config = character_language_openai_role_config(
            {request.character_model_class: request.character_model},
            reasoning_by_effort={
                request.character_reasoning_effort: request.character_reasoning_effort.value
            },
        )
        configs: tuple[OpenAIResponsesRoleConfig, ...] = (character_config,)
        if request.run_semantic_verification:
            configs += _semantic_role_configs(
                request.semantic_model,
                request.semantic_model_class,
                request.semantic_reasoning_effort,
            )
        return OpenAIResponsesAdapter.from_environment(configs)

    async def _run_once_same_plan(
        self,
        request: CharacterLanguageLabRequest,
        plan: SpeechSemanticPlan,
        profile: CharacterLanguageProfile,
        source: Mapping[str, object],
        recorder: _RecordingPort,
        priors: tuple[CharacterLanguagePriorRealizationView, ...],
        repetition_index: int,
    ) -> tuple[dict[str, object], CharacterUtterance | None]:
        run_id = f"character-language-run-{uuid4().hex}"
        snapshot = CharacterLanguageContextSnapshot(
            f"character-request-{uuid4().hex}",
            plan,
            profile,
            (),
            LLMPriority.FOREGROUND,
            LLMInterruptibility.INTERRUPTIBLE,
            datetime.now(timezone.utc),
            f"character-trace-{uuid4().hex}",
            priors,
        )
        prior_projection = snapshot.to_dict()["prior_realizations"]
        character_policy = CharacterLanguagePolicy(
            _execution_policy(
                request.character_model_class,
                request.character_reasoning_effort,
                request,
            )
        )
        realizer = CharacterLanguageRealizer(
            recorder,
            _StaticCharacterLiveState(),
            CharacterLanguageAuthority(),
            character_policy,
        )
        started = perf_counter()
        try:
            utterance = await realizer.realize(
                snapshot,
                utterance_id=f"utterance-{uuid4().hex}",
                created_at=datetime.now(timezone.utc),
            )
        except Exception as error:
            return (
                {
                    "ok": False,
                    "run_id": run_id,
                    "repetition_index": repetition_index,
                    "status": CharacterLanguageLabStatus.CHARACTER_COMMIT_REJECTED.value,
                    "error_type": type(error).__name__,
                    "semantic_plan": plan.to_dict(),
                    "prior_realizations_used": prior_projection,
                    "character_profile": _profile_dict(profile),
                    "character_source_kind": source.get("kind"),
                    "character_latency_ms": round((perf_counter() - started) * 1000, 3),
                },
                None,
            )
        character_latency = round((perf_counter() - started) * 1000, 3)
        semantic_result: dict[str, object] | None = None
        if request.run_semantic_verification:
            semantic_result = await self._verify_semantics(
                request,
                plan,
                utterance,
                recorder,
            )
        return (
            {
                "ok": semantic_result is None or bool(semantic_result.get("ok")),
                "run_id": run_id,
                "repetition_index": repetition_index,
                "status": CharacterLanguageLabStatus.COMPLETED.value,
                "semantic_plan": plan.to_dict(),
                "prior_realizations_used": prior_projection,
                "character_profile": _profile_dict(profile),
                "character_utterance": utterance.to_dict(),
                "character_latency_ms": character_latency,
                "semantic_verification": semantic_result,
                "human_evaluation": None,
            },
            utterance,
        )


def _append_unique_prior(
    priors: tuple[CharacterLanguagePriorRealizationView, ...],
    value: CharacterLanguagePriorRealizationView,
) -> tuple[CharacterLanguagePriorRealizationView, ...]:
    if any(item.text == value.text for item in priors):
        return priors
    return (*priors, value)[-MAX_PRIOR_REALIZATIONS:]


__all__ = ["StrictSamePlanCharacterLanguageLabService"]
