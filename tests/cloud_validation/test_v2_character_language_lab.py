from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from app.domain.contracts.common import JsonValue, thaw_json
from app.domain.llm import (
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from cloud_validation.v2_character_language_lab import (
    CharacterLanguageLabMode,
    CharacterLanguageLabRequest,
    CharacterLanguageLabService,
    CharacterLanguageLabSettings,
    CharacterLanguageLabStatus,
)


class FakeCharacterPort:
    def __init__(self) -> None:
        self.calls: list[LLMRoleRequest] = []

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.calls.append(request)
        if request.role_id != "character_language":
            raise AssertionError(f"unexpected role: {request.role_id}")
        payload = thaw_json(request.input.value)
        assert isinstance(payload, dict)
        semantic_plan = payload["semantic_plan"]
        character_profile = payload["character_profile"]
        assert isinstance(semantic_plan, dict)
        assert isinstance(character_profile, dict)
        plan_candidate = semantic_plan["candidate"]
        assert isinstance(plan_candidate, dict)
        propositions = plan_candidate["propositions"]
        assert isinstance(propositions, list)
        proposition = propositions[0]
        assert isinstance(proposition, dict)
        output: JsonValue = cast(
            JsonValue,
            {
                "candidate_id": f"candidate-{len(self.calls)}",
                "request_id": request.request_id,
                "semantic_plan_id": semantic_plan["plan_id"],
                "source_decision_id": plan_candidate["decision_id"],
                "source_intent_id": plan_candidate["intent_id"],
                "source_event_ids": plan_candidate["source_event_ids"],
                "revisions": plan_candidate["revisions"],
                "character_id": character_profile["character_id"],
                "character_schema_version": character_profile["schema_version"],
                "character_definition_revision": character_profile[
                    "definition_revision"
                ],
                "segments": [
                    {
                        "segment_id": "segment-1",
                        "text": "うん、分かったよ。",
                        "realization_refs": [proposition["proposition_id"]],
                        "boundary_after": "sentence",
                        "emphasis": "neutral",
                        "hesitation": "none",
                    }
                ],
                "question_budget_used": 0,
                "new_direction_budget_used": 0,
            },
        )
        return LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.SUCCEEDED,
            request.revisions,
            request.created_at + timedelta(seconds=1),
            request.trace_id,
            request.execution_policy.model_class,
            1,
            LLMTokenUsage(100, 20),
            StructuredPayload("character.language.candidate.v1", output),
            started_at=request.created_at,
        )


def _settings(path: Path) -> CharacterLanguageLabSettings:
    return CharacterLanguageLabSettings(path, "model-character", "model-semantic", "test-head")


def _request(
    mode: CharacterLanguageLabMode,
    *,
    repetitions: int = 1,
) -> CharacterLanguageLabRequest:
    return CharacterLanguageLabRequest(
        mode,
        "neutral_fact",
        repetitions,
        "model-character",
        LLMModelClass.BALANCED,
        LLMReasoningEffort.MEDIUM,
        "model-semantic",
        LLMModelClass.BALANCED,
        LLMReasoningEffort.MEDIUM,
        run_semantic_verification=False,
    )


def _production_yaml() -> str:
    return """schema_version: 1
character_id: yura
definition_revision: 3
authority:
  bible_path: docs/character/v2/yura_character_bible.md
  owner_issue: 354
identity: []
dispositions: []
deep_priors: []
formative_history: []
beliefs: []
values: []
preferences: []
self_model: []
narrative_identity: []
adaptations: []
language:
  - id: baseline_softness
    state: confirmed
    value: やわらかく自然体
voice: []
body: []
"""


def test_integrated_readiness_blocks_when_production_definition_is_missing(
    tmp_path: Path,
) -> None:
    port = FakeCharacterPort()
    service = CharacterLanguageLabService(
        _settings(tmp_path / "missing.yaml"),
        port,
    )

    readiness = service.readiness()
    assert readiness["status"] == (
        CharacterLanguageLabStatus.BLOCKED_UPSTREAM_CHARACTER_DEFINITION.value
    )
    assert readiness["integrated_ready"] is False

    result = asyncio.run(service.run(_request(CharacterLanguageLabMode.INTEGRATED)))
    assert result["ok"] is False
    assert result["integrated_evidence_eligible"] is False
    assert result["runs"] == []
    assert port.calls == []


def test_isolation_run_never_promotes_to_integrated_evidence(tmp_path: Path) -> None:
    port = FakeCharacterPort()
    service = CharacterLanguageLabService(
        _settings(tmp_path / "missing.yaml"),
        port,
    )

    result = asyncio.run(
        service.run(_request(CharacterLanguageLabMode.ISOLATION, repetitions=2))
    )

    assert result["ok"] is True
    assert result["status"] == CharacterLanguageLabStatus.COMPLETED.value
    assert result["evidence_class"] == "isolation_only"
    assert result["integrated_evidence_eligible"] is False
    runs = result["runs"]
    assert isinstance(runs, list)
    assert len(runs) == 2
    assert len({item["run_id"] for item in runs}) == 2
    assert len(port.calls) == 2


def test_integrated_run_uses_production_yaml_loader_and_projection(tmp_path: Path) -> None:
    definition = tmp_path / "yura.yaml"
    definition.write_text(_production_yaml(), encoding="utf-8")
    port = FakeCharacterPort()
    service = CharacterLanguageLabService(_settings(definition), port)

    readiness = service.readiness()
    assert readiness["status"] == CharacterLanguageLabStatus.READY.value
    assert readiness["integrated_ready"] is True
    source = readiness["character_source"]
    assert isinstance(source, dict)
    profile = source["profile"]
    assert isinstance(profile, dict)
    assert profile["definition_revision"] == 3
    facets = profile["facets"]
    assert isinstance(facets, list)
    assert facets[0]["facet_id"] == "baseline_softness"
    assert facets[0]["availability"] == "confirmed"

    result = asyncio.run(service.run(_request(CharacterLanguageLabMode.INTEGRATED)))
    assert result["ok"] is True
    assert result["evidence_class"] == "integrated"
    assert result["integrated_evidence_eligible"] is True
    assert len(port.calls) == 1
    runs = result["runs"]
    assert isinstance(runs, list)
    run = runs[0]
    assert run["human_evaluation"] is None
    semantic_plan = run["semantic_plan"]
    assert isinstance(semantic_plan, dict)
    assert semantic_plan["plan_id"].startswith("speech-plan-")


@pytest.mark.parametrize("repetitions", [0, 11])
def test_repetition_count_is_bounded(repetitions: int) -> None:
    with pytest.raises(ValueError, match="repetitions"):
        _request(CharacterLanguageLabMode.ISOLATION, repetitions=repetitions)


def test_multimodal_model_class_is_rejected() -> None:
    with pytest.raises(ValueError, match="MULTIMODAL"):
        CharacterLanguageLabRequest(
            CharacterLanguageLabMode.ISOLATION,
            "neutral_fact",
            1,
            "model-character",
            LLMModelClass.MULTIMODAL,
            LLMReasoningEffort.MEDIUM,
            "model-semantic",
            LLMModelClass.BALANCED,
            LLMReasoningEffort.MEDIUM,
            run_semantic_verification=False,
        )
