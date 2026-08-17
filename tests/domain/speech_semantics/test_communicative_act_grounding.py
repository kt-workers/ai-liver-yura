from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.contracts import RevisionVector
from app.domain.executive import (
    CommittedExecutiveDecision,
    ExecutiveDecisionCandidate,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveInterruptibility,
    ExecutiveOutcome,
    ExecutivePriority,
    SpeechIntentPayload,
)
from app.domain.speech_semantics import (
    SelfDisclosurePolicy,
    SemanticCertainty,
    SemanticPolarity,
    SpeechProposition,
    SpeechPropositionDisposition,
    SpeechSemanticAuthority,
    SpeechSemanticCandidate,
    SpeechSemanticContextSnapshot,
    SpeechSemanticFact,
    SpeechSemanticFactKind,
)

NOW = datetime(2026, 8, 17, 13, 0, tzinfo=timezone.utc)
REVISIONS = RevisionVector(20, 7, 3)


def _decision() -> CommittedExecutiveDecision:
    assert REVISIONS.goal_revision is not None
    assert REVISIONS.attention_revision is not None
    intent = ExecutiveIntent(
        "intent-communicative",
        ExecutiveIntentKind.SPEECH,
        "相手への謝意を伝える",
        SpeechIntentPayload("fact-gratitude"),
        (),
        (),
        (),
        (),
    )
    candidate = ExecutiveDecisionCandidate(
        "decision-candidate",
        "trigger-1",
        ("event-1",),
        REVISIONS.source_context_revision,
        REVISIONS.goal_revision,
        REVISIONS.attention_revision,
        ExecutiveOutcome.RESPOND,
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (intent,),
        (),
        (),
        ("fact-gratitude",),
        NOW,
    )
    return CommittedExecutiveDecision("decision-1", candidate, (), NOW)


def _facts() -> tuple[SpeechSemanticFact, SpeechSemanticFact]:
    communicative = SpeechSemanticFact(
        "fact-gratitude",
        SpeechSemanticFactKind.DISCOURSE,
        "current-interaction",
        "communicative-act",
        {"kind": "gratitude", "target_ref": "user"},
        polarity=SemanticPolarity.AFFIRM,
        certainty=SemanticCertainty.CERTAIN,
    )
    unrelated = SpeechSemanticFact(
        "fact-unrelated",
        SpeechSemanticFactKind.GENERAL,
        "topic",
        "continuation",
        {"allowed": True},
        polarity=SemanticPolarity.AFFIRM,
        certainty=SemanticCertainty.CERTAIN,
    )
    return communicative, unrelated


def _context() -> SpeechSemanticContextSnapshot:
    return SpeechSemanticContextSnapshot(
        _decision(),
        "intent-communicative",
        _facts(),
        (),
        (),
        SelfDisclosurePolicy.FACT_GROUNDED,
        0,
        0,
        NOW,
    )


def test_communicative_act_fact_can_be_committed_as_required_proposition() -> None:
    communicative, _ = _facts()
    proposition = SpeechProposition(
        "prop-gratitude",
        communicative.subject_ref,
        communicative.predicate,
        communicative.value,
        SpeechPropositionDisposition.REQUIRED,
        communicative.polarity,
        communicative.certainty,
        (communicative.fact_id,),
    )
    candidate = SpeechSemanticCandidate(
        "semantic-candidate",
        "decision-1",
        "intent-communicative",
        ("event-1",),
        REVISIONS,
        (proposition,),
        SelfDisclosurePolicy.FACT_GROUNDED,
        0,
        0,
        (),
        (),
        (),
        NOW,
    )

    plan = SpeechSemanticAuthority().commit(
        candidate,
        _context(),
        current_revisions=REVISIONS,
        plan_id="plan-communicative",
        committed_at=NOW,
    )

    assert plan.candidate.propositions == (proposition,)
    assert plan.candidate.propositions[0].disposition is SpeechPropositionDisposition.REQUIRED


def test_communicative_semantic_goal_cannot_be_omitted_from_plan() -> None:
    _, unrelated = _facts()
    unrelated_proposition = SpeechProposition(
        "prop-unrelated",
        unrelated.subject_ref,
        unrelated.predicate,
        unrelated.value,
        SpeechPropositionDisposition.OPTIONAL,
        unrelated.polarity,
        unrelated.certainty,
        (unrelated.fact_id,),
    )
    candidate = SpeechSemanticCandidate(
        "semantic-candidate",
        "decision-1",
        "intent-communicative",
        ("event-1",),
        REVISIONS,
        (unrelated_proposition,),
        SelfDisclosurePolicy.FACT_GROUNDED,
        0,
        0,
        (),
        (),
        (),
        NOW,
    )

    with pytest.raises(ValueError):
        SpeechSemanticAuthority().commit(
            candidate,
            _context(),
            current_revisions=REVISIONS,
            plan_id="plan-missing-communicative-goal",
            committed_at=NOW,
        )
