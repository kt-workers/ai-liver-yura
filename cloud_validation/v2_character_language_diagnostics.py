from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.domain.character_language import CharacterUtterance
from app.domain.llm import LLMInterruptibility, LLMPriority
from app.domain.semantic_verification import (
    SemanticVerificationAuthority,
    SemanticVerificationContextSnapshot,
    SemanticVerificationError,
    SemanticVerificationPolicy,
    SemanticVerifier,
)
from app.domain.speech_semantics import SpeechSemanticPlan
from cloud_validation.v2_character_language_lab import (
    CharacterLanguageLabRequest,
    CharacterLanguageLabService,
    CharacterLanguageLabStatus,
    _execution_policy,
    _RecordingPort,
    _StaticSemanticLiveState,
)

_MAX_DOMAIN_MESSAGE_LENGTH = 500


def semantic_failure_diagnostic(
    error: Exception,
    *,
    latency_ms: float,
) -> dict[str, object]:
    """#434 Exportへsecretを含めずDomain failureの識別情報だけを残す。"""

    value: dict[str, object] = {
        "ok": False,
        "status": CharacterLanguageLabStatus.SEMANTIC_VERIFICATION_FAILED.value,
        "error_type": type(error).__name__,
        "latency_ms": latency_ms,
    }
    if isinstance(error, SemanticVerificationError):
        value["error_code"] = error.code.value
        value["error_message"] = str(error)[:_MAX_DOMAIN_MESSAGE_LENGTH]
    elif isinstance(error, ValueError):
        value["error_code"] = None
        value["error_message"] = str(error)[:_MAX_DOMAIN_MESSAGE_LENGTH]
    return value


class DiagnosticCharacterLanguageLabService(CharacterLanguageLabService):
    """production #363 policyを変えず、#434向けfailure provenanceだけ追加する。"""

    async def _verify_semantics(
        self,
        request: CharacterLanguageLabRequest,
        plan: SpeechSemanticPlan,
        utterance: CharacterUtterance,
        recorder: _RecordingPort,
    ) -> dict[str, object]:
        snapshot = SemanticVerificationContextSnapshot(
            f"verification-{uuid4().hex}",
            f"blind-request-{uuid4().hex}",
            f"relation-request-{uuid4().hex}",
            plan,
            utterance,
            LLMPriority.FOREGROUND,
            LLMInterruptibility.INTERRUPTIBLE,
            datetime.now(timezone.utc),
            f"semantic-trace-{uuid4().hex}",
        )
        policy = SemanticVerificationPolicy(
            _execution_policy(
                request.semantic_model_class,
                request.semantic_reasoning_effort,
                request,
            ),
            _execution_policy(
                request.semantic_model_class,
                request.semantic_reasoning_effort,
                request,
            ),
        )
        verifier = SemanticVerifier(
            recorder,
            _StaticSemanticLiveState(),
            SemanticVerificationAuthority(),
            policy,
        )
        started = perf_counter()
        try:
            run = await verifier.verify(
                snapshot,
                blind_observation_id=f"blind-observation-{uuid4().hex}",
                relation_observation_id=f"relation-observation-{uuid4().hex}",
                semantic_observation_id=f"semantic-observation-{uuid4().hex}",
                acceptance_id=f"acceptance-{uuid4().hex}",
                created_at=datetime.now(timezone.utc),
            )
        except Exception as error:
            return semantic_failure_diagnostic(
                error,
                latency_ms=round((perf_counter() - started) * 1000, 3),
            )
        return {
            "ok": True,
            "status": run.acceptance.state.value,
            "rejection_categories": [
                item.value for item in run.acceptance.rejection_categories
            ],
            "blind_observation": run.blind_observation.to_dict(),
            "blind_provider_result": run.blind_result.to_dict(),
            "relation_provider_result": run.relation_result.to_dict(),
            "latency_ms": round((perf_counter() - started) * 1000, 3),
        }


__all__ = [
    "DiagnosticCharacterLanguageLabService",
    "semantic_failure_diagnostic",
]
