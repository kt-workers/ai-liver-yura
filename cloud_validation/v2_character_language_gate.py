from __future__ import annotations

from typing import cast

from cloud_validation.v2_character_language_lab import (
    CharacterLanguageLabMode,
    CharacterLanguageLabRequest,
    CharacterLanguageLabService,
)


class CharacterLanguageLabGate:
    """Lab engineの実行結果をrelease evidenceへ昇格させる境界。"""

    def __init__(self, service: CharacterLanguageLabService) -> None:
        self._service = service

    def readiness(self) -> dict[str, object]:
        value = dict(self._service.readiness())
        value["human_evaluation_required"] = True
        value["integrated_evidence_eligible"] = False
        return value

    async def run(self, request: CharacterLanguageLabRequest) -> dict[str, object]:
        result = dict(await self._service.run(request))
        if request.mode is CharacterLanguageLabMode.ISOLATION:
            result["evidence_class"] = "isolation_only"
            result["integrated_machine_gate_passed"] = False
            result["integrated_evidence_eligible"] = False
            result["human_evaluation_required"] = False
            return result

        semantic_pass = request.run_semantic_verification and self._semantic_all_accepted(
            result
        )
        execution_pass = bool(result.get("ok")) and semantic_pass
        result["ok"] = execution_pass
        result["evidence_class"] = (
            "integrated_pending_human" if execution_pass else "integrated_incomplete"
        )
        result["integrated_machine_gate_passed"] = execution_pass
        result["integrated_evidence_eligible"] = False
        result["human_evaluation_required"] = True
        if not request.run_semantic_verification:
            result["gate_blocker"] = "SEMANTIC_VERIFICATION_REQUIRED"
        elif not semantic_pass:
            result["gate_blocker"] = "SEMANTIC_ACCEPTANCE_REQUIRED"
        else:
            result["gate_blocker"] = "HUMAN_CHARACTER_EVALUATION_REQUIRED"
        return result

    @staticmethod
    def _semantic_all_accepted(result: dict[str, object]) -> bool:
        runs_value = result.get("runs")
        if not isinstance(runs_value, list) or not runs_value:
            return False
        for run_value in runs_value:
            if not isinstance(run_value, dict):
                return False
            semantic_value = run_value.get("semantic_verification")
            if not isinstance(semantic_value, dict):
                return False
            if semantic_value.get("status") != "accepted":
                return False
            if semantic_value.get("ok") is not True:
                return False
        return True


__all__ = ["CharacterLanguageLabGate"]
