from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast

import pytest

from app.domain.semantic_verification import (
    BlindSemanticUnit,
    BlindSemanticUnitKind,
    BlindUnitAccounting,
    BlindUnitAccountingRelation,
    BlindUtteranceObservation,
    CertaintyRelation,
    DegreeRelation,
    ExecutionRelation,
    PlanRelationObservationCandidate,
    PolarityRelation,
    PropositionRelation,
    PropositionSemanticObservation,
    SelfDisclosureRelation,
    SemanticAcceptanceState,
    SemanticRejectionCategory,
    SemanticVerificationAuthority,
    SemanticVerificationContextSnapshot,
    SpeechActBudgetObservation,
    UtteranceEvidenceRef,
    relation_instructions,
)
from app.domain.speech_semantics import SpeechPropositionDisposition

NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)


def _snapshot() -> SemanticVerificationContextSnapshot:
    proposition = SimpleNamespace(
        proposition_id="p1",
        disposition=SpeechPropositionDisposition.REQUIRED,
    )
    candidate = SimpleNamespace(
        propositions=(proposition,),
        question_budget=0,
        new_direction_budget=0,
    )
    plan = SimpleNamespace(plan_id="plan-1", candidate=candidate)
    utterance = SimpleNamespace(utterance_id="utterance-1")
    return cast(
        SemanticVerificationContextSnapshot,
        SimpleNamespace(
            verification_id="verification-1",
            relation_request_id="relation-request-1",
            semantic_plan=plan,
            utterance=utterance,
        ),
    )


def _blind() -> BlindUtteranceObservation:
    evidence = UtteranceEvidenceRef("segment-1", "actual contradiction", 0)
    unit = BlindSemanticUnit(
        "unit-1",
        BlindSemanticUnitKind.MATERIAL_SEMANTIC_CONTENT,
        (),
        (evidence,),
    )
    return cast(
        BlindUtteranceObservation,
        SimpleNamespace(observation_id="blind-observation-1", units=(unit,)),
    )


def _candidate(
    *, relation: PropositionRelation, support: bool
) -> PlanRelationObservationCandidate:
    evidence = UtteranceEvidenceRef("segment-1", "actual contradiction", 0)
    support_ids = ("unit-1",) if support else ()
    proposition_evidence = (evidence,) if relation is not PropositionRelation.MISSING else ()
    return PlanRelationObservationCandidate(
        "candidate-1",
        "relation-request-1",
        "plan-1",
        "utterance-1",
        "blind-observation-1",
        (
            PropositionSemanticObservation(
                "p1",
                relation,
                PolarityRelation.PRESERVED,
                CertaintyRelation.PRESERVED,
                DegreeRelation.NOT_APPLICABLE,
                ExecutionRelation.CONTRADICTED,
                proposition_evidence,
                support_ids,
            ),
        ),
        (
            BlindUnitAccounting(
                "unit-1",
                BlindUnitAccountingRelation.SUPPORTED_BY_PLAN,
                ("p1",),
                (evidence,),
            ),
        ),
        SpeechActBudgetObservation(0, 0),
        SelfDisclosureRelation.NOT_APPLICABLE,
        NOW,
    )


def test_relation_instruction_treats_contradiction_as_plan_grounded() -> None:
    instructions = relation_instructions()

    assert "ENTAILEDまたはCONTRADICTED" in instructions
    assert "CONTRADICTEDでも同じPlan proposition" in instructions
    assert "UNSUPPORTED_EXTRAへ落としてはいけません" in instructions


def test_contradicted_grounding_rejects_without_unsupported_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SemanticVerificationAuthority,
        "_validate_all_evidence",
        lambda *args, **kwargs: None,
    )
    snapshot = _snapshot()
    blind = _blind()
    authority = SemanticVerificationAuthority()

    relation = authority.commit_relation(
        _candidate(relation=PropositionRelation.CONTRADICTED, support=True),
        snapshot,
        blind,
        observation_id="relation-observation-1",
        committed_at=NOW,
    )
    _, acceptance = authority.reconcile(
        snapshot,
        blind,
        relation,
        observation_id="semantic-observation-1",
        acceptance_id="acceptance-1",
        committed_at=NOW,
    )

    assert acceptance.state is SemanticAcceptanceState.REJECTED
    assert acceptance.rejection_categories == (
        SemanticRejectionCategory.PROPOSITION_CONTRADICTED,
    )


def test_missing_proposition_cannot_receive_plan_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SemanticVerificationAuthority,
        "_validate_all_evidence",
        lambda *args, **kwargs: None,
    )
    snapshot = _snapshot()
    blind = _blind()

    with pytest.raises(ValueError, match="MISSING / AMBIGUOUS"):
        SemanticVerificationAuthority().commit_relation(
            _candidate(relation=PropositionRelation.MISSING, support=True),
            snapshot,
            blind,
            observation_id="relation-observation-1",
            committed_at=NOW,
        )
