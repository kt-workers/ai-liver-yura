from __future__ import annotations

import asyncio
from typing import cast

from app.domain.llm import LLMModelClass, LLMReasoningEffort
from cloud_validation.v2_character_language_gate import CharacterLanguageLabGate
from cloud_validation.v2_character_language_lab import (
    CharacterLanguageLabMode,
    CharacterLanguageLabRequest,
    CharacterLanguageLabService,
)


class StubEngine:
    def __init__(self, result: dict[str, object]) -> None:
        self._result = result

    def readiness(self) -> dict[str, object]:
        return {"integrated_ready": True, "status": "READY"}

    async def run(self, request: CharacterLanguageLabRequest) -> dict[str, object]:
        return dict(self._result)


def _request(
    mode: CharacterLanguageLabMode,
    *,
    semantic: bool = True,
) -> CharacterLanguageLabRequest:
    return CharacterLanguageLabRequest(
        mode,
        "neutral_fact",
        1,
        "character-model",
        LLMModelClass.BALANCED,
        LLMReasoningEffort.MEDIUM,
        "semantic-model",
        LLMModelClass.BALANCED,
        LLMReasoningEffort.MEDIUM,
        run_semantic_verification=semantic,
    )


def _gate(result: dict[str, object]) -> CharacterLanguageLabGate:
    engine = cast(CharacterLanguageLabService, StubEngine(result))
    return CharacterLanguageLabGate(engine)


def test_readiness_never_claims_integrated_evidence_before_human_evaluation() -> None:
    readiness = _gate({}).readiness()
    assert readiness["human_evaluation_required"] is True
    assert readiness["integrated_evidence_eligible"] is False


def test_isolation_never_promotes_to_integrated_evidence() -> None:
    result = asyncio.run(
        _gate({"ok": True, "runs": []}).run(_request(CharacterLanguageLabMode.ISOLATION))
    )
    assert result["ok"] is True
    assert result["evidence_class"] == "isolation_only"
    assert result["integrated_machine_gate_passed"] is False
    assert result["integrated_evidence_eligible"] is False


def test_integrated_requires_semantic_verification_to_be_enabled() -> None:
    result = asyncio.run(
        _gate({"ok": True, "runs": [{"semantic_verification": None}]}).run(
            _request(CharacterLanguageLabMode.INTEGRATED, semantic=False)
        )
    )
    assert result["ok"] is False
    assert result["evidence_class"] == "integrated_incomplete"
    assert result["integrated_machine_gate_passed"] is False
    assert result["integrated_evidence_eligible"] is False
    assert result["gate_blocker"] == "SEMANTIC_VERIFICATION_REQUIRED"


def test_integrated_rejects_semantically_rejected_actual_utterance() -> None:
    result = asyncio.run(
        _gate(
            {
                "ok": True,
                "runs": [
                    {
                        "semantic_verification": {
                            "ok": True,
                            "status": "rejected",
                        }
                    }
                ],
            }
        ).run(_request(CharacterLanguageLabMode.INTEGRATED))
    )
    assert result["ok"] is False
    assert result["integrated_machine_gate_passed"] is False
    assert result["integrated_evidence_eligible"] is False
    assert result["gate_blocker"] == "SEMANTIC_ACCEPTANCE_REQUIRED"


def test_integrated_acceptance_still_waits_for_human_character_evaluation() -> None:
    result = asyncio.run(
        _gate(
            {
                "ok": True,
                "runs": [
                    {
                        "semantic_verification": {
                            "ok": True,
                            "status": "accepted",
                        }
                    }
                ],
            }
        ).run(_request(CharacterLanguageLabMode.INTEGRATED))
    )
    assert result["ok"] is True
    assert result["evidence_class"] == "integrated_pending_human"
    assert result["integrated_machine_gate_passed"] is True
    assert result["integrated_evidence_eligible"] is False
    assert result["human_evaluation_required"] is True
    assert result["gate_blocker"] == "HUMAN_CHARACTER_EVALUATION_REQUIRED"
