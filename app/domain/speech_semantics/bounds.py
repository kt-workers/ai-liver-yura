from __future__ import annotations

import json
from dataclasses import replace
from enum import Enum
from typing import Protocol

from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts.common import thaw_json
from app.domain.executive import SpeechIntentPayload

from .contracts import (
    DeterministicSpeechDirective,
    SpeechSemanticCandidate,
    SpeechSemanticContextSnapshot,
    SpeechSemanticFact,
)


class SpeechSemanticBoundsFailureCode(str, Enum):
    CONTEXT_TOO_LARGE = "speech_semantic_context_too_large"
    OUTPUT_TOO_LARGE = "speech_semantic_output_too_large"
    POLICY_STALE = "speech_semantic_policy_stale"


class SpeechSemanticBoundsError(ValueError):
    def __init__(self, code: SpeechSemanticBoundsFailureCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


class SpeechSemanticBoundsPolicyPort(Protocol):
    async def current_policy(
        self, snapshot: SpeechSemanticContextSnapshot
    ) -> BrainOperationalBoundsPolicy: ...


def _require_policy(bounds_policy: BrainOperationalBoundsPolicy) -> BrainOperationalBoundsPolicy:
    if not isinstance(bounds_policy, BrainOperationalBoundsPolicy):
        raise ValueError("容量方針はBrainOperationalBoundsPolicyでなければなりません")
    return bounds_policy


def _canonical_json_utf8_bytes(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _fact_payload_bytes(fact: SpeechSemanticFact) -> int:
    return _canonical_json_utf8_bytes(thaw_json(fact.value))


def assert_speech_semantic_policy_generation(
    expected: BrainOperationalBoundsPolicy,
    current: BrainOperationalBoundsPolicy,
) -> None:
    expected_policy = _require_policy(expected)
    current_policy = _require_policy(current)
    if (
        expected_policy.policy_id != current_policy.policy_id
        or expected_policy.policy_revision != current_policy.policy_revision
    ):
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.POLICY_STALE,
            "Speech Semantics request generationとcurrent policy generationが一致しません",
        )


def validate_speech_semantic_context_bounds(
    snapshot: SpeechSemanticContextSnapshot,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> None:
    if not isinstance(snapshot, SpeechSemanticContextSnapshot):
        raise ValueError("snapshotはSpeechSemanticContextSnapshotでなければなりません")
    bounds = _require_policy(bounds_policy).speech_semantics
    checks = (
        ("facts", len(snapshot.facts), bounds.max_facts),
        ("truth_constraints", len(snapshot.truth_constraints), bounds.max_truth_constraints),
        (
            "available_constraint_refs",
            len(snapshot.available_constraint_refs),
            bounds.max_relationship_constraints + bounds.max_discourse_constraints,
        ),
    )
    for name, actual, maximum in checks:
        if actual > maximum:
            raise SpeechSemanticBoundsError(
                SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE,
                f"{name} count={actual} limit={maximum}",
            )
    if snapshot.max_question_budget > bounds.max_question_budget:
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE,
            (
                f"max_question_budget={snapshot.max_question_budget} "
                f"limit={bounds.max_question_budget}"
            ),
        )
    if snapshot.max_new_direction_budget > bounds.max_new_direction_budget:
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE,
            (
                f"max_new_direction_budget={snapshot.max_new_direction_budget} "
                f"limit={bounds.max_new_direction_budget}"
            ),
        )
    for fact in snapshot.facts:
        payload_bytes = _fact_payload_bytes(fact)
        if payload_bytes > bounds.max_fact_payload_json_bytes:
            raise SpeechSemanticBoundsError(
                SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE,
                (
                    f"fact_id={fact.fact_id} payload_bytes={payload_bytes} "
                    f"limit={bounds.max_fact_payload_json_bytes}"
                ),
            )


def build_bounded_speech_semantic_context(
    snapshot: SpeechSemanticContextSnapshot,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> SpeechSemanticContextSnapshot:
    if not isinstance(snapshot, SpeechSemanticContextSnapshot):
        raise ValueError("snapshotはSpeechSemanticContextSnapshotでなければなりません")
    policy = _require_policy(bounds_policy)
    bounds = policy.speech_semantics
    if len(snapshot.truth_constraints) > bounds.max_truth_constraints:
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE,
            "authoritative truth constraints exceed speech semantic capacity",
        )
    if len(snapshot.available_constraint_refs) > (
        bounds.max_relationship_constraints + bounds.max_discourse_constraints
    ):
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE,
            "available constraint refs exceed speech semantic capacity",
        )
    if (
        snapshot.max_question_budget > bounds.max_question_budget
        or snapshot.max_new_direction_budget > bounds.max_new_direction_budget
    ):
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE,
            "authoritative speech budget exceeds technical capacity",
        )

    intent = snapshot.intent
    payload = intent.payload
    assert isinstance(payload, SpeechIntentPayload)
    required_fact_ids = {
        payload.semantic_goal_ref,
        *intent.evidence_refs,
        *intent.forbidden_claim_refs,
        *(constraint.fact_ref for constraint in snapshot.truth_constraints),
    }
    if payload.target_ref is not None:
        required_fact_ids.add(payload.target_ref)
    facts_by_id = {item.fact_id: item for item in snapshot.facts}
    required = tuple(item for item in snapshot.facts if item.fact_id in required_fact_ids)
    if set(required_fact_ids) - set(facts_by_id):
        raise ValueError("required speech fact is outside source snapshot")
    if len(required) > bounds.max_facts:
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE,
            "required speech facts exceed speech semantic capacity",
        )
    for fact in required:
        payload_bytes = _fact_payload_bytes(fact)
        if payload_bytes > bounds.max_fact_payload_json_bytes:
            raise SpeechSemanticBoundsError(
                SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE,
                f"required fact payload is too large: {fact.fact_id}",
            )
    remaining = sorted(
        (item for item in snapshot.facts if item.fact_id not in required_fact_ids),
        key=lambda item: (item.kind.value, item.fact_id),
    )
    selected: list[SpeechSemanticFact] = list(required)
    for fact in remaining:
        if len(selected) >= bounds.max_facts:
            break
        if _fact_payload_bytes(fact) <= bounds.max_fact_payload_json_bytes:
            selected.append(fact)
    bounded = replace(snapshot, facts=tuple(selected))
    validate_speech_semantic_context_bounds(bounded, policy)
    return bounded


def validate_speech_semantic_output_bounds(
    value: SpeechSemanticCandidate | DeterministicSpeechDirective,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> None:
    if not isinstance(value, (SpeechSemanticCandidate, DeterministicSpeechDirective)):
        raise ValueError("speech semantic outputの型が不正です")
    bounds = _require_policy(bounds_policy).speech_semantics
    if len(value.propositions) > bounds.max_propositions:
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.OUTPUT_TOO_LARGE,
            f"propositions count={len(value.propositions)} limit={bounds.max_propositions}",
        )
    for proposition in value.propositions:
        if len(proposition.evidence_fact_refs) > bounds.max_evidence_refs_per_proposition:
            raise SpeechSemanticBoundsError(
                SpeechSemanticBoundsFailureCode.OUTPUT_TOO_LARGE,
                (
                    f"proposition={proposition.proposition_id} evidence_refs="
                    f"{len(proposition.evidence_fact_refs)} "
                    f"limit={bounds.max_evidence_refs_per_proposition}"
                ),
            )
    if len(value.relationship_constraint_refs) > bounds.max_relationship_constraints:
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.OUTPUT_TOO_LARGE,
            "relationship constraint refs exceed speech semantic capacity",
        )
    if len(value.discourse_constraint_refs) > bounds.max_discourse_constraints:
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.OUTPUT_TOO_LARGE,
            "discourse constraint refs exceed speech semantic capacity",
        )
    total_constraint_refs = (
        len(value.truth_constraint_refs)
        + len(value.relationship_constraint_refs)
        + len(value.discourse_constraint_refs)
    )
    if total_constraint_refs > bounds.max_constraint_refs_per_plan:
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.OUTPUT_TOO_LARGE,
            (
                f"constraint refs count={total_constraint_refs} "
                f"limit={bounds.max_constraint_refs_per_plan}"
            ),
        )
    if value.question_budget > bounds.max_question_budget:
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.OUTPUT_TOO_LARGE,
            f"question_budget={value.question_budget} limit={bounds.max_question_budget}",
        )
    if value.new_direction_budget > bounds.max_new_direction_budget:
        raise SpeechSemanticBoundsError(
            SpeechSemanticBoundsFailureCode.OUTPUT_TOO_LARGE,
            (
                f"new_direction_budget={value.new_direction_budget} "
                f"limit={bounds.max_new_direction_budget}"
            ),
        )
