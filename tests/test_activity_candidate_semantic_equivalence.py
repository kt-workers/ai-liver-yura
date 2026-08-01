from __future__ import annotations

import pytest

from app.domain.morals import (
    ActivityCandidateSemanticEquivalenceEvaluator,
    ActivityCandidateSemanticEquivalenceEvidence,
    SemanticEquivalenceDimension,
    SemanticEquivalenceStatus,
)


def _confirmed_evidence(
    candidate_group: tuple[str, ...],
    *,
    evidence_id: str | None = "semantic-evidence-1",
    source: str = "situation_evaluator_shadow",
) -> ActivityCandidateSemanticEquivalenceEvidence:
    return ActivityCandidateSemanticEquivalenceEvidence(
        candidate_group=candidate_group,
        intent=SemanticEquivalenceDimension.CONFIRMED,
        operation=SemanticEquivalenceDimension.CONFIRMED,
        goal=SemanticEquivalenceDimension.CONFIRMED,
        source=source,
        evidence_id=evidence_id,
    )


def test_semantic_equivalence_is_unconfirmed_without_typed_evidence() -> None:
    result = ActivityCandidateSemanticEquivalenceEvaluator().evaluate(
        ("conversation_with_user", "autonomous_talk")
    )

    assert result.status is SemanticEquivalenceStatus.UNCONFIRMED
    assert result.confirmed is False
    assert result.source == "unavailable"
    assert "semantic_equivalence_evidence_unavailable" in result.reasons


def test_semantic_equivalence_is_confirmed_only_when_all_dimensions_match() -> None:
    candidate_group = ("conversation_with_user", "autonomous_talk")
    result = ActivityCandidateSemanticEquivalenceEvaluator().evaluate(
        candidate_group,
        _confirmed_evidence(candidate_group),
    )

    assert result.status is SemanticEquivalenceStatus.CONFIRMED
    assert result.confirmed is True
    assert result.intent is SemanticEquivalenceDimension.CONFIRMED
    assert result.operation is SemanticEquivalenceDimension.CONFIRMED
    assert result.goal is SemanticEquivalenceDimension.CONFIRMED
    assert result.evidence_id == "semantic-evidence-1"
    assert "semantic_equivalence_confirmed" in result.reasons


def test_semantic_equivalence_is_rejected_when_any_dimension_is_rejected() -> None:
    candidate_group = ("conversation_with_user", "autonomous_talk")
    evidence = ActivityCandidateSemanticEquivalenceEvidence(
        candidate_group=candidate_group,
        intent=SemanticEquivalenceDimension.REJECTED,
        operation=SemanticEquivalenceDimension.CONFIRMED,
        goal=SemanticEquivalenceDimension.CONFIRMED,
        source="situation_evaluator_shadow",
        evidence_id="semantic-evidence-2",
    )

    result = ActivityCandidateSemanticEquivalenceEvaluator().evaluate(
        candidate_group,
        evidence,
    )

    assert result.status is SemanticEquivalenceStatus.REJECTED
    assert result.confirmed is False
    assert "semantic_equivalence_rejected" in result.reasons


def test_semantic_equivalence_requires_provenance_for_confirmation() -> None:
    candidate_group = ("conversation_with_user", "autonomous_talk")
    result = ActivityCandidateSemanticEquivalenceEvaluator().evaluate(
        candidate_group,
        _confirmed_evidence(
            candidate_group,
            evidence_id=None,
            source="unavailable",
        ),
    )

    assert result.status is SemanticEquivalenceStatus.UNCONFIRMED
    assert result.confirmed is False
    assert "semantic_equivalence_provenance_missing" in result.reasons


def test_semantic_equivalence_rejects_stale_candidate_group_evidence() -> None:
    result = ActivityCandidateSemanticEquivalenceEvaluator().evaluate(
        ("conversation_with_user", "autonomous_talk"),
        _confirmed_evidence(
            ("conversation_with_user", "plugin_activity")
        ),
    )

    assert result.status is SemanticEquivalenceStatus.UNCONFIRMED
    assert result.confirmed is False
    assert "semantic_equivalence_candidate_group_mismatch" in result.reasons


def test_semantic_equivalence_evidence_requires_unique_candidate_group() -> None:
    with pytest.raises(ValueError, match="must not contain duplicates"):
        ActivityCandidateSemanticEquivalenceEvidence(
            candidate_group=(
                "conversation_with_user",
                "conversation_with_user",
            )
        )
