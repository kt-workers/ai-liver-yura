from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from app.domain.contracts.common import JsonValue, thaw_json
from app.domain.llm import (
    LLMFailureCode,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from app.usecases.ports.llm import LLMRolePort
from cloud_validation.v2_character_language_lab import (
    CharacterLanguageLabMode,
    CharacterLanguageLabRequest,
    CharacterLanguageLabSettings,
)
from cloud_validation.v2_character_language_same_plan import (
    StrictSamePlanCharacterLanguageLabService,
)


class SequencedCharacterPort:
    def __init__(self, texts: tuple[str, ...]) -> None:
        self._texts = texts
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
        text = self._texts[min(len(self.calls) - 1, len(self._texts) - 1)]
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
                        "text": text,
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
            request.created_at,
            request.trace_id,
            request.execution_policy.model_class,
            1,
            LLMTokenUsage(100, 20),
            StructuredPayload("character.language.candidate.v1", output),
            started_at=request.created_at,
        )


class FailedCharacterPort:
    def __init__(self) -> None:
        self.calls: list[LLMRoleRequest] = []

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.calls.append(request)
        return LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.FAILED,
            request.revisions,
            request.created_at,
            request.trace_id,
            request.execution_policy.model_class,
            1,
            LLMTokenUsage(0, 0),
            failure=LLMRoleFailure(
                LLMFailureCode.SCHEMA_INVALID,
                "safe schema diagnostic",
            ),
        )


def _service(
    tmp_path: Path,
    port: LLMRolePort,
) -> StrictSamePlanCharacterLanguageLabService:
    settings = CharacterLanguageLabSettings(
        tmp_path / "missing.yaml",
        "model-character",
        "model-semantic",
        "test-head",
    )
    return StrictSamePlanCharacterLanguageLabService(settings, port)


def _request(repetitions: int) -> CharacterLanguageLabRequest:
    return CharacterLanguageLabRequest(
        CharacterLanguageLabMode.ISOLATION,
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


def _prior_texts(request: LLMRoleRequest) -> list[str]:
    payload = thaw_json(request.input.value)
    assert isinstance(payload, dict)
    priors = payload["prior_realizations"]
    assert isinstance(priors, list)
    result: list[str] = []
    for item in priors:
        assert isinstance(item, dict)
        text = item["text"]
        assert isinstance(text, str)
        result.append(text)
    return result


def test_repeated_variants_use_one_exact_plan_and_bounded_priors(tmp_path: Path) -> None:
    port = SequencedCharacterPort(("表現A", "表現B", "表現C", "表現D", "表現E"))
    result = asyncio.run(_service(tmp_path, port).run(_request(5)))

    runs = result["runs"]
    assert isinstance(runs, list)
    plan_ids = {
        cast(dict[str, object], run["semantic_plan"])["plan_id"]
        for run in runs
        if isinstance(run, dict)
    }
    assert len(plan_ids) == 1
    batch = result["variation_batch"]
    assert isinstance(batch, dict)
    assert batch["strict_same_plan"] is True
    assert batch["semantic_plan_id"] in plan_ids
    assert batch["max_prior_realizations"] == 3

    assert len(port.calls) == 5
    assert all(call.input.schema_id == "character.language.context.v2" for call in port.calls)
    assert _prior_texts(port.calls[0]) == []
    assert _prior_texts(port.calls[1]) == ["表現A"]
    assert _prior_texts(port.calls[2]) == ["表現A", "表現B"]
    assert _prior_texts(port.calls[3]) == ["表現A", "表現B", "表現C"]
    assert _prior_texts(port.calls[4]) == ["表現B", "表現C", "表現D"]

    for index, run in enumerate(runs):
        assert isinstance(run, dict)
        request_payload = thaw_json(port.calls[index].input.value)
        assert isinstance(request_payload, dict)
        assert run["prior_realizations_used"] == request_payload["prior_realizations"]


def test_exact_duplicate_output_is_not_duplicated_in_prior_list(tmp_path: Path) -> None:
    port = SequencedCharacterPort(("同じ表現", "同じ表現", "別表現", "さらに別表現"))
    result = asyncio.run(_service(tmp_path, port).run(_request(4)))

    assert result["ok"] is True
    assert _prior_texts(port.calls[0]) == []
    assert _prior_texts(port.calls[1]) == ["同じ表現"]
    assert _prior_texts(port.calls[2]) == ["同じ表現"]
    assert _prior_texts(port.calls[3]) == ["同じ表現", "別表現"]


def test_strict_same_plan_exports_provider_failure_without_prior_or_semantic_run(
    tmp_path: Path,
) -> None:
    port = FailedCharacterPort()
    result = asyncio.run(_service(tmp_path, port).run(_request(1)))

    runs = result["runs"]
    assert isinstance(runs, list)
    run = runs[0]
    assert run["status"] == "PROVIDER_FAILED"
    assert run["provider_result_status"] == "failed"
    assert run["failure_code"] == "schema_invalid"
    assert run["prior_realizations_used"] == []
    assert "character_utterance" not in run
    assert "semantic_verification" not in run
