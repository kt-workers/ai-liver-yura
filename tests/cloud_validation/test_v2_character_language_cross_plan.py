from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest

from app.domain.llm import LLMModelClass, LLMReasoningEffort
from app.usecases.ports.llm import LLMRolePort
from cloud_validation.v2_character_language_cross_plan import (
    CrossPlanConversationCharacterLanguageLabService,
)
from cloud_validation.v2_character_language_lab import (
    CharacterLanguageLabMode,
    CharacterLanguageLabProbe,
    CharacterLanguageLabRequest,
    CharacterLanguageLabSettings,
)
from tests.cloud_validation.test_v2_character_language_same_plan import (
    SequencedCharacterPort,
    _prior_texts,
)


class ControlledSemanticCrossPlanService(CrossPlanConversationCharacterLanguageLabService):
    def __init__(
        self,
        settings: CharacterLanguageLabSettings,
        port: LLMRolePort,
        statuses: tuple[str, ...],
    ) -> None:
        super().__init__(settings, port)
        self._statuses = statuses
        self._semantic_calls = 0

    async def _verify_semantics(self, *args: object, **kwargs: object) -> dict[str, object]:
        status = self._statuses[self._semantic_calls]
        self._semantic_calls += 1
        return {"ok": status == "accepted", "status": status}


def _request(scenario_id: str = "gratitude") -> CharacterLanguageLabRequest:
    return CharacterLanguageLabRequest(
        CharacterLanguageLabMode.ISOLATION,
        scenario_id,
        5,
        "model-character",
        LLMModelClass.BALANCED,
        LLMReasoningEffort.MEDIUM,
        "model-semantic",
        LLMModelClass.BALANCED,
        LLMReasoningEffort.MEDIUM,
        probe=CharacterLanguageLabProbe.CROSS_PLAN_CONVERSATION,
    )


def _service(
    tmp_path: Path,
    port: LLMRolePort,
    statuses: tuple[str, ...],
) -> ControlledSemanticCrossPlanService:
    return ControlledSemanticCrossPlanService(
        CharacterLanguageLabSettings(
            tmp_path / "missing.yaml",
            "model-character",
            "model-semantic",
            "test-head",
        ),
        port,
        statuses,
    )


def test_cross_plan_commits_five_distinct_gratitude_context_plans(tmp_path: Path) -> None:
    port = SequencedCharacterPort(("A", "B", "C", "D", "E"))
    result = asyncio.run(_service(tmp_path, port, ("accepted",) * 5).run(_request()))

    assert result["evidence_class"] == "isolation_only"
    assert result["integrated_evidence_eligible"] is False
    assert result["scenario_set"] == "gratitude_conversation_v1"
    assert result["model_policy"] == {
        "character": {
            "provider_model": "model-character",
            "model_class": "balanced",
            "reasoning_effort": "medium",
            "provider_format": "character_language_candidate_v1",
        },
        "semantic": {
            "enabled": True,
            "provider_model": "model-semantic",
            "model_class": "balanced",
            "reasoning_effort": "medium",
        },
    }
    assert result["conversation"] == {
        "turns": 5,
        "prior_realizations": "各turnは空。same-Plan専用provenance契約を越えない",
    }
    runs = cast(list[dict[str, object]], result["runs"])
    assert len({cast(dict[str, object], run["semantic_plan"])["plan_id"] for run in runs}) == 5
    plan_reasons = []
    for run in runs:
        semantic_plan = cast(dict[str, object], run["semantic_plan"])
        candidate = cast(dict[str, object], semantic_plan["candidate"])
        proposition = cast(list[dict[str, object]], candidate["propositions"])[0]
        value = cast(dict[str, object], proposition["value"])
        plan_reasons.append(value["reason"])
    assert plan_reasons == [
        "作業を手伝ってもらった",
        "情報を教えてもらった",
        "待ってもらった",
        "修正してもらった",
        "結果を確認してもらった",
    ]
    assert [
        cast(dict[str, object], run["conversation_turn"])["context_summary"] for run in runs
    ] == [
        "作業を手伝ってもらった",
        "情報を教えてもらった",
        "待ってもらった",
        "修正してもらった",
        "結果を確認してもらった",
    ]
    assert all(call.input.schema_id == "character.language.context.v2" for call in port.calls)
    assert len(port.calls) == 5
    assert all(_prior_texts(call) == [] for call in port.calls)


def test_cross_plan_runs_semantic_verification_independently_without_prior_history(
    tmp_path: Path,
) -> None:
    port = SequencedCharacterPort(("A", "B", "C", "D", "E"))
    result = asyncio.run(
        _service(
            tmp_path,
            port,
            ("accepted", "rejected", "SEMANTIC_VERIFICATION_FAILED", "accepted", "accepted"),
        ).run(_request())
    )

    runs = cast(list[dict[str, object]], result["runs"])
    assert [cast(dict[str, object], run["semantic_verification"])["status"] for run in runs] == [
        "accepted",
        "rejected",
        "SEMANTIC_VERIFICATION_FAILED",
        "accepted",
        "accepted",
    ]
    assert _prior_texts(port.calls[0]) == []
    assert all(_prior_texts(call) == [] for call in port.calls)


def test_cross_plan_rejects_non_gratitude_scenario(tmp_path: Path) -> None:
    port = SequencedCharacterPort(("A",))

    with pytest.raises(ValueError, match="scenario_idはgratitude"):
        asyncio.run(_service(tmp_path, port, ("accepted",) * 5).run(_request("degree")))
