from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from threading import Lock

from app.domain.character_language import CharacterUtterance
from app.domain.speech_semantics import SpeechPropositionDisposition

from .contracts import (
    _ACCEPTANCE_PROOF,
    _BLIND_PROOF,
    _OBSERVATION_PROOF,
    _RELATION_PROOF,
    BlindSemanticUnitKind,
    BlindUnitAccountingRelation,
    BlindUtteranceObservation,
    BlindUtteranceObservationCandidate,
    CertaintyRelation,
    DegreeRelation,
    ExecutionRelation,
    PlanRelationObservation,
    PlanRelationObservationCandidate,
    PolarityRelation,
    PropositionRelation,
    SemanticAcceptance,
    SemanticAcceptanceState,
    SemanticRejectionCategory,
    SemanticRelationObservation,
    SemanticVerificationContextSnapshot,
    SelfDisclosureRelation,
    UtteranceEvidenceRef,
)


_SAFE_POLARITY = frozenset({PolarityRelation.PRESERVED, PolarityRelation.NOT_APPLICABLE})
_SAFE_CERTAINTY = frozenset({CertaintyRelation.PRESERVED, CertaintyRelation.NOT_APPLICABLE})
_SAFE_DEGREE = frozenset({DegreeRelation.PRESERVED, DegreeRelation.NOT_APPLICABLE})
_SAFE_EXECUTION = frozenset({ExecutionRelation.PRESERVED, ExecutionRelation.NOT_APPLICABLE})


class SemanticVerificationAuthority:
    """LLM観測候補をexact utteranceへgroundし、closed policyでacceptanceを導出する。"""

    def __init__(self) -> None:
        self._blind_ids: set[str] = set()
        self._relation_ids: set[str] = set()
        self._observation_ids: set[str] = set()
        self._acceptance_ids: set[str] = set()
        self._lock = Lock()

    def commit_blind(
        self,
        candidate: BlindUtteranceObservationCandidate,
        snapshot: SemanticVerificationContextSnapshot,
        *,
        observation_id: str,
        committed_at: datetime,
    ) -> BlindUtteranceObservation:
        if candidate.request_id != snapshot.blind_request_id:
            raise ValueError("blind request identityが一致しません")
        if candidate.utterance_id != snapshot.utterance.utterance_id:
            raise ValueError("blind utterance identityが一致しません")
        self._validate_all_evidence(
            snapshot.utterance,
            (ref for unit in candidate.units for ref in unit.evidence_refs),
        )
        with self._lock:
            if observation_id in self._blind_ids:
                raise ValueError("blind observation_id はすでにcommitされています")
            self._blind_ids.add(observation_id)
        return BlindUtteranceObservation(
            observation_id,
            candidate,
            committed_at,
            _proof=_BLIND_PROOF,
        )

    def commit_relation(
        self,
        candidate: PlanRelationObservationCandidate,
        snapshot: SemanticVerificationContextSnapshot,
        blind: BlindUtteranceObservation,
        *,
        observation_id: str,
        committed_at: datetime,
    ) -> PlanRelationObservation:
        if candidate.request_id != snapshot.relation_request_id:
            raise ValueError("relation request identityが一致しません")
        if candidate.semantic_plan_id != snapshot.semantic_plan.plan_id:
            raise ValueError("relation plan identityが一致しません")
        if candidate.utterance_id != snapshot.utterance.utterance_id:
            raise ValueError("relation utterance identityが一致しません")
        if candidate.blind_observation_id != blind.observation_id:
            raise ValueError("relation blind observation identityが一致しません")

        plan_ids = {item.proposition_id for item in snapshot.semantic_plan.candidate.propositions}
        observed_ids = {item.proposition_id for item in candidate.proposition_observations}
        if observed_ids != plan_ids:
            raise ValueError("Plan propositionごとにexactly one observationが必要です")

        blind_by_id = {item.unit_id: item for item in blind.units}
        accounting_ids = {item.blind_unit_id for item in candidate.blind_unit_accounting}
        if accounting_ids != set(blind_by_id):
            raise ValueError("blind unitごとにexactly one accountingが必要です")

        for observation in candidate.proposition_observations:
            if any(unit_id not in blind_by_id for unit_id in observation.supporting_blind_unit_ids):
                raise ValueError("unknown blind unitがproposition relationへ参照されています")
            self._validate_all_evidence(snapshot.utterance, observation.evidence_refs)
            supporting_evidence = {
                self._evidence_key(ref)
                for unit_id in observation.supporting_blind_unit_ids
                for ref in blind_by_id[unit_id].evidence_refs
            }
            if observation.relation is PropositionRelation.ENTAILED:
                if not observation.supporting_blind_unit_ids:
                    raise ValueError("ENTAILED propositionにはblind unit supportが必要です")
                if any(
                    self._evidence_key(ref) not in supporting_evidence
                    for ref in observation.evidence_refs
                ):
                    raise ValueError("proposition evidenceはsupporting blind unitへgroundする必要があります")

        for accounting in candidate.blind_unit_accounting:
            unit = blind_by_id[accounting.blind_unit_id]
            if any(item not in plan_ids for item in accounting.proposition_ids):
                raise ValueError("blind unit accountingがunknown propositionを参照しています")
            self._validate_all_evidence(snapshot.utterance, accounting.evidence_refs)
            own_evidence = {self._evidence_key(ref) for ref in unit.evidence_refs}
            if any(self._evidence_key(ref) not in own_evidence for ref in accounting.evidence_refs):
                raise ValueError("blind unit accounting evidenceは元unitへgroundする必要があります")
            if (
                unit.kind is BlindSemanticUnitKind.MATERIAL_CLAIM
                and accounting.relation
                is BlindUnitAccountingRelation.PERMITTED_NON_PROPOSITIONAL_STYLE
            ):
                raise ValueError("MATERIAL_CLAIMをstyleへ降格できません")
            if (
                accounting.relation is BlindUnitAccountingRelation.SUPPORTED_BY_PLAN
                and not accounting.proposition_ids
            ):
                raise ValueError("SUPPORTED_BY_PLANにはproposition参照が必要です")

        with self._lock:
            if observation_id in self._relation_ids:
                raise ValueError("relation observation_id はすでにcommitされています")
            self._relation_ids.add(observation_id)
        return PlanRelationObservation(
            observation_id,
            candidate,
            committed_at,
            _proof=_RELATION_PROOF,
        )

    def reconcile(
        self,
        snapshot: SemanticVerificationContextSnapshot,
        blind: BlindUtteranceObservation,
        relation: PlanRelationObservation,
        *,
        observation_id: str,
        acceptance_id: str,
        committed_at: datetime,
    ) -> tuple[SemanticRelationObservation, SemanticAcceptance]:
        candidate = relation.candidate
        categories: set[SemanticRejectionCategory] = set()
        plan_by_id = {
            item.proposition_id: item for item in snapshot.semantic_plan.candidate.propositions
        }
        observations = {
            item.proposition_id: item for item in candidate.proposition_observations
        }
        accounting = {
            item.blind_unit_id: item for item in candidate.blind_unit_accounting
        }

        for proposition_id, proposition in plan_by_id.items():
            observed = observations[proposition_id]
            if proposition.disposition is SpeechPropositionDisposition.REQUIRED:
                if observed.relation is PropositionRelation.MISSING:
                    categories.add(SemanticRejectionCategory.REQUIRED_PROPOSITION_MISSING)
                elif observed.relation is PropositionRelation.CONTRADICTED:
                    categories.add(SemanticRejectionCategory.PROPOSITION_CONTRADICTED)
                elif observed.relation is PropositionRelation.AMBIGUOUS:
                    categories.add(SemanticRejectionCategory.AMBIGUOUS_SEMANTIC_OBSERVATION)
                elif not observed.supporting_blind_unit_ids:
                    categories.add(SemanticRejectionCategory.OBSERVER_DISAGREEMENT)
            elif proposition.disposition is SpeechPropositionDisposition.OPTIONAL:
                if observed.relation is PropositionRelation.CONTRADICTED:
                    categories.add(SemanticRejectionCategory.PROPOSITION_CONTRADICTED)
                elif observed.relation is PropositionRelation.AMBIGUOUS:
                    categories.add(SemanticRejectionCategory.AMBIGUOUS_SEMANTIC_OBSERVATION)
            elif observed.relation in {PropositionRelation.ENTAILED, PropositionRelation.AMBIGUOUS}:
                categories.add(SemanticRejectionCategory.FORBIDDEN_PROPOSITION_REALIZED)

            if observed.relation is PropositionRelation.ENTAILED:
                if observed.polarity_relation not in _SAFE_POLARITY:
                    categories.add(SemanticRejectionCategory.POLARITY_CHANGED)
                if observed.certainty_relation not in _SAFE_CERTAINTY:
                    categories.add(SemanticRejectionCategory.CERTAINTY_CHANGED)
                if observed.degree_relation not in _SAFE_DEGREE:
                    categories.add(SemanticRejectionCategory.DEGREE_CHANGED)
                if observed.execution_relation not in _SAFE_EXECUTION:
                    categories.add(SemanticRejectionCategory.EXECUTION_TRUTH_CHANGED)

        for unit in blind.units:
            item = accounting[unit.unit_id]
            if unit.kind is BlindSemanticUnitKind.AMBIGUOUS:
                categories.add(SemanticRejectionCategory.AMBIGUOUS_SEMANTIC_OBSERVATION)
            if unit.kind is BlindSemanticUnitKind.MATERIAL_CLAIM:
                if item.relation is BlindUnitAccountingRelation.UNSUPPORTED_EXTRA:
                    categories.add(SemanticRejectionCategory.UNSUPPORTED_EXTRA_CLAIM)
                elif item.relation is BlindUnitAccountingRelation.AMBIGUOUS:
                    categories.add(SemanticRejectionCategory.AMBIGUOUS_SEMANTIC_OBSERVATION)
                elif item.relation is not BlindUnitAccountingRelation.SUPPORTED_BY_PLAN:
                    categories.add(SemanticRejectionCategory.UNACCOUNTED_MATERIAL_CLAIM)
            elif unit.kind is BlindSemanticUnitKind.NON_PROPOSITIONAL_STYLE:
                if item.relation is not BlindUnitAccountingRelation.PERMITTED_NON_PROPOSITIONAL_STYLE:
                    categories.add(SemanticRejectionCategory.OBSERVER_DISAGREEMENT)
            elif unit.kind in {
                BlindSemanticUnitKind.DIRECTED_QUESTION,
                BlindSemanticUnitKind.NEW_DIRECTION,
            }:
                if item.relation is not BlindUnitAccountingRelation.QUESTION_OR_DIRECTION:
                    categories.add(SemanticRejectionCategory.OBSERVER_DISAGREEMENT)

        a_questions = sum(
            1 for unit in blind.units if unit.kind is BlindSemanticUnitKind.DIRECTED_QUESTION
        )
        a_directions = sum(
            1 for unit in blind.units if unit.kind is BlindSemanticUnitKind.NEW_DIRECTION
        )
        budget = candidate.budget_observation
        if budget.directed_question_count != a_questions or budget.new_direction_count != a_directions:
            categories.add(SemanticRejectionCategory.OBSERVER_DISAGREEMENT)
        plan_candidate = snapshot.semantic_plan.candidate
        if budget.directed_question_count > plan_candidate.question_budget:
            categories.add(SemanticRejectionCategory.QUESTION_BUDGET_EXCEEDED)
        if budget.new_direction_count > plan_candidate.new_direction_budget:
            categories.add(SemanticRejectionCategory.NEW_DIRECTION_BUDGET_EXCEEDED)
        if candidate.self_disclosure_relation is SelfDisclosureRelation.EXCEEDED:
            categories.add(SemanticRejectionCategory.SELF_DISCLOSURE_EXCEEDED)
        elif candidate.self_disclosure_relation is SelfDisclosureRelation.AMBIGUOUS:
            categories.add(SemanticRejectionCategory.AMBIGUOUS_SEMANTIC_OBSERVATION)

        ordered = tuple(sorted(categories, key=lambda item: item.value))
        with self._lock:
            if observation_id in self._observation_ids:
                raise ValueError("SemanticRelationObservation IDはすでにcommitされています")
            if acceptance_id in self._acceptance_ids:
                raise ValueError("SemanticAcceptance IDはすでにcommitされています")
            self._observation_ids.add(observation_id)
            self._acceptance_ids.add(acceptance_id)

        observation = SemanticRelationObservation(
            observation_id,
            snapshot.verification_id,
            blind.observation_id,
            relation.observation_id,
            snapshot.semantic_plan.plan_id,
            snapshot.utterance.utterance_id,
            ordered,
            committed_at,
            _proof=_OBSERVATION_PROOF,
        )
        state = SemanticAcceptanceState.ACCEPTED if not ordered else SemanticAcceptanceState.REJECTED
        acceptance = SemanticAcceptance(
            acceptance_id,
            observation.observation_id,
            snapshot.semantic_plan.plan_id,
            snapshot.utterance.utterance_id,
            state,
            ordered,
            committed_at,
            _proof=_ACCEPTANCE_PROOF,
        )
        return observation, acceptance

    @staticmethod
    def _evidence_key(ref: UtteranceEvidenceRef) -> tuple[str, str, int]:
        return ref.segment_id, ref.quote, ref.occurrence_index

    @classmethod
    def _validate_all_evidence(
        cls,
        utterance: CharacterUtterance,
        refs: Iterable[UtteranceEvidenceRef],
    ) -> None:
        segments = {item.segment_id: item.text for item in utterance.candidate.segments}
        for ref in refs:
            text = segments.get(ref.segment_id)
            if text is None:
                raise ValueError("unknown segmentへevidenceが参照されています")
            positions: list[int] = []
            start = 0
            while True:
                index = text.find(ref.quote, start)
                if index < 0:
                    break
                positions.append(index)
                start = index + 1
            if ref.occurrence_index >= len(positions):
                raise ValueError("evidence quote occurrenceをactual utteranceへgroundできません")
