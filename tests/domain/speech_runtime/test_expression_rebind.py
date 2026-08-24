from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.llm import LLMInterruptibility, LLMPriority
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SemanticVerificationRequirement,
    SpeechComponentReadiness,
    SpeechPresentationMode,
    SpeechReadinessState,
    VerifierReadinessState,
)
from app.domain.speech_runtime.runtime import SpeechRuntime


def _candidate() -> PreparedSpeechCandidate:
    now = datetime.now(timezone.utc)
    return PreparedSpeechCandidate(
        candidate_id="candidate",
        preparation_id="preparation",
        source_decision_id="decision",
        source_event_ids=("event",),
        speech_plan_id="plan",
        utterance_id="utterance",
        performance_plan_id="performance-g1",
        source_context_revision=1,
        goal_revision=1,
        attention_revision=1,
        priority=LLMPriority.FOREGROUND,
        interruptibility=LLMInterruptibility.INTERRUPTIBLE,
        expiry_policy_ref="expiry",
        required_preconditions=(),
        semantic_requirement=SemanticVerificationRequirement.REQUIRED,
        semantic_acceptance_id="acceptance",
        prepared_audio_ref="audio-g1",
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.READY,
        ),
        lifecycle=CandidateLifecycle.PREPARED,
        created_at=now,
        updated_at=now,
        expression_revision=1,
    )


@pytest.mark.asyncio
async def test_expression_only_rebind_preserves_utterance_semantics_and_rejects_old_results() -> (
    None
):
    runtime = SpeechRuntime()
    await runtime.register(_candidate())
    generation = await runtime.rebind_performance_for_expression("candidate", 2)
    rebound = await runtime.candidate("candidate")
    assert generation == 2
    assert rebound.utterance_id == "utterance"
    assert rebound.speech_plan_id == "plan"
    assert rebound.semantic_acceptance_id == "acceptance"
    assert rebound.repair_count == 0
    assert rebound.performance_plan_id is None
    assert rebound.prepared_audio_ref is None
    assert rebound.performance_generation == 2
    assert rebound.expression_revision == 2
    late = await runtime.commit_generation_result(
        "candidate",
        1,
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.READY,
        ),
        performance_plan_id="late-performance",
        prepared_audio_ref="late-audio",
    )
    assert late is None
    current = await runtime.candidate("candidate")
    assert current.performance_plan_id is None
    assert current.prepared_audio_ref is None
