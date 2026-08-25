from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.domain.llm import LLMInterruptibility, LLMPriority
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SemanticVerificationRequirement,
    SemanticVerificationRequirementPolicy,
    SemanticVerificationSkipProof,
    SpeechComponentReadiness,
    SpeechPreparationRequest,
    SpeechPresentationMode,
    SpeechReadinessState,
    VerifierReadinessState,
)


def _proof(policy_id: str = "semantic-policy", revision: int = 7) -> SemanticVerificationSkipProof:
    return SemanticVerificationSkipProof(policy_id, revision, "closed-policy", ("condition",))


def _policy(
    proof: SemanticVerificationSkipProof | None = None,
) -> SemanticVerificationRequirementPolicy:
    accepted = proof or _proof()
    return SemanticVerificationRequirementPolicy(
        accepted.policy_id, accepted.policy_revision, (accepted,)
    )


def _request(**changes: object) -> SpeechPreparationRequest:
    values: dict[str, object] = {
        "preparation_id": "preparation",
        "source_decision_id": "decision",
        "speech_intent_ref": "intent",
        "source_event_ids": ("event",),
        "source_context_revision": 1,
        "goal_revision": None,
        "attention_revision": None,
        "priority": LLMPriority.FOREGROUND,
        "interruptibility": LLMInterruptibility.INTERRUPTIBLE,
        "required_preconditions": (),
        "expiry_policy_ref": "expiry",
        "semantic_verification_requirement": (
            SemanticVerificationRequirement.NOT_REQUIRED_BY_CLOSED_POLICY
        ),
        "semantic_verification_policy_ref": "semantic-policy",
        "semantic_verification_policy_revision": 7,
        "presentation_policy_ref": "presentation-policy",
        "created_at": datetime.now(timezone.utc),
        "trace_id": "trace",
        "semantic_skip_proof": _proof(),
        "semantic_verification_policy": _policy(),
    }
    values.update(changes)
    return SpeechPreparationRequest(**values)  # type: ignore[arg-type]


def _candidate(**changes: object) -> PreparedSpeechCandidate:
    now = datetime.now(timezone.utc)
    values: dict[str, object] = {
        "candidate_id": "candidate",
        "preparation_id": "preparation",
        "source_decision_id": "decision",
        "source_event_ids": ("event",),
        "speech_plan_id": "plan",
        "utterance_id": "utterance",
        "performance_plan_id": "performance",
        "source_context_revision": 1,
        "goal_revision": None,
        "attention_revision": None,
        "priority": LLMPriority.FOREGROUND,
        "interruptibility": LLMInterruptibility.INTERRUPTIBLE,
        "expiry_policy_ref": "expiry",
        "required_preconditions": (),
        "semantic_requirement": SemanticVerificationRequirement.NOT_REQUIRED_BY_CLOSED_POLICY,
        "semantic_acceptance_id": None,
        "prepared_audio_ref": None,
        "presentation_modes": (SpeechPresentationMode.TEXT_ONLY,),
        "readiness": SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.NOT_REQUIRED,
            SpeechReadinessState.READY,
            AudioReadinessState.NOT_REQUESTED,
        ),
        "lifecycle": CandidateLifecycle.PREPARED,
        "created_at": now,
        "updated_at": now,
        "semantic_skip_proof": _proof(),
        "semantic_verification_policy_ref": "semantic-policy",
        "semantic_verification_policy_revision": 7,
        "semantic_verification_policy": _policy(),
    }
    values.update(changes)
    return PreparedSpeechCandidate(**values)  # type: ignore[arg-type]


def test_closed_policy_skip_proof_is_bound_to_request_generation_policy() -> None:
    assert _request().semantic_skip_proof == _proof()
    with pytest.raises(ValueError, match="proof"):
        _request(semantic_skip_proof=None)
    with pytest.raises(ValueError, match="binding"):
        _request(semantic_skip_proof=_proof("other-policy"), semantic_verification_policy=_policy())
    with pytest.raises(ValueError, match="binding"):
        _request(semantic_skip_proof=_proof(revision=8), semantic_verification_policy=_policy())
    with pytest.raises(ValueError, match="binding"):
        _request(
            semantic_skip_proof=SemanticVerificationSkipProof(
                "semantic-policy", 7, "wrong-reason", ("condition",)
            ),
            semantic_verification_policy=_policy(),
        )
    with pytest.raises(ValueError, match="binding"):
        _request(
            semantic_skip_proof=SemanticVerificationSkipProof(
                "semantic-policy", 7, "closed-policy", ("wrong-condition",)
            ),
            semantic_verification_policy=_policy(),
        )


def test_closed_policy_skip_proof_is_bound_to_candidate_generation_policy() -> None:
    candidate = _candidate()
    assert candidate.semantic_skip_proof == _proof()
    with pytest.raises(ValueError, match="proof"):
        replace(candidate, semantic_skip_proof=None)
    with pytest.raises(ValueError, match="binding"):
        replace(candidate, semantic_verification_policy_revision=8)
    with pytest.raises(ValueError, match="binding"):
        replace(
            candidate,
            semantic_skip_proof=SemanticVerificationSkipProof(
                "semantic-policy", 7, "wrong-reason", ("condition",)
            ),
        )


def test_required_verifier_cannot_be_replaced_by_caller_supplied_skip_proof() -> None:
    with pytest.raises(ValueError, match="REQUIRED"):
        _request(
            semantic_verification_requirement=SemanticVerificationRequirement.REQUIRED,
        )
    with pytest.raises(ValueError, match="REQUIRED"):
        _candidate(semantic_requirement=SemanticVerificationRequirement.REQUIRED)
