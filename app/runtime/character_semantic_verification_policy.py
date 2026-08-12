from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.semantic_utterance import SemanticProposition, SemanticUtterancePlan
from app.domain.semantic_validation import CharacterSemanticVerification


@dataclass(frozen=True, slots=True)
class SemanticVerificationDifference:
    proposition_id: str | None
    facet: str
    relation: str
    repair: str

    def as_context(self) -> dict[str, str | None]:
        return {
            "proposition_id": self.proposition_id,
            "facet": self.facet,
            "relation": self.relation,
            "repair": self.repair,
        }


@dataclass(frozen=True, slots=True)
class CharacterSemanticDecision:
    accepted: bool
    reason: str
    differences: tuple[SemanticVerificationDifference, ...] = field(default_factory=tuple)

    def as_context(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "differences": [item.as_context() for item in self.differences],
        }


class CharacterSemanticVerificationPolicy:
    """LLMのrelative relationから最終accept/rejectを閉じた規則で導出する。"""

    def decide(
        self,
        plan: SemanticUtterancePlan,
        verification: CharacterSemanticVerification,
        *,
        speech: str,
    ) -> CharacterSemanticDecision:
        expected_by_id = {item.proposition_id: item for item in plan.propositions}
        actual_by_id = {item.proposition_id: item for item in verification.propositions}

        differences: list[SemanticVerificationDifference] = []
        missing = sorted(set(expected_by_id) - set(actual_by_id))
        extra = sorted(set(actual_by_id) - set(expected_by_id))
        for proposition_id in missing:
            differences.append(
                SemanticVerificationDifference(
                    proposition_id,
                    "verification",
                    "missing",
                    "reverify_required_proposition",
                )
            )
        for proposition_id in extra:
            differences.append(
                SemanticVerificationDifference(
                    proposition_id,
                    "verification",
                    "unexpected",
                    "remove_unplanned_verification_result",
                )
            )

        for proposition_id, proposition in expected_by_id.items():
            item = actual_by_id.get(proposition_id)
            if item is None:
                continue
            for span in item.evidence_spans:
                if span not in speech:
                    differences.append(
                        SemanticVerificationDifference(
                            proposition_id,
                            "evidence",
                            "not_in_speech",
                            "reverify_with_real_speech_span",
                        )
                    )

            if proposition.realization_policy == "optional" and not item.realized:
                self._validate_optional_omission(proposition, item, differences)
                continue

            if not item.realized:
                differences.append(
                    SemanticVerificationDifference(
                        proposition_id,
                        "realization",
                        "omitted",
                        "restore_required_proposition",
                    )
                )
                continue

            self._validate_realized_proposition(proposition, item, differences)

        for field_name, value, repair in (
            (
                "required_content",
                verification.required_content_preserved,
                "restore_required_content",
            ),
            (
                "forbidden_additions",
                verification.forbidden_additions_absent,
                "remove_forbidden_additions",
            ),
            (
                "unsupported_new_fact",
                verification.unsupported_new_fact_absent,
                "remove_unsupported_new_fact",
            ),
            (
                "existence_boundary",
                verification.existence_boundary_preserved,
                "restore_existence_boundary",
            ),
            (
                "budget",
                verification.budget_preserved,
                "restore_response_budget",
            ),
        ):
            if not value:
                differences.append(
                    SemanticVerificationDifference(None, field_name, "violated", repair)
                )

        for span in verification.global_evidence_spans:
            if span not in speech:
                differences.append(
                    SemanticVerificationDifference(
                        None,
                        "global_evidence",
                        "not_in_speech",
                        "reverify_with_real_speech_span",
                    )
                )

        return CharacterSemanticDecision(
            accepted=not differences,
            reason=(
                "character_semantics_preserved"
                if not differences
                else "character_semantics_changed"
            ),
            differences=tuple(differences),
        )

    @staticmethod
    def _validate_optional_omission(
        proposition: SemanticProposition,
        item: object,
        differences: list[SemanticVerificationDifference],
    ) -> None:
        # Avoid importing the concrete class solely for annotation; attributes are schema-validated.
        relations = {
            "predicate": getattr(item, "predicate_relation"),
            "value_status": getattr(item, "value_status_relation"),
            "polarity": getattr(item, "polarity_relation"),
            "degree": getattr(item, "degree_relation"),
            "certainty": getattr(item, "certainty_relation"),
            "concept": getattr(item, "concept_relation"),
            "summary": getattr(item, "summary_relation"),
        }
        if relations["predicate"] != "omitted":
            differences.append(
                SemanticVerificationDifference(
                    proposition.proposition_id,
                    "predicate",
                    str(relations["predicate"]),
                    "mark_optional_proposition_omitted",
                )
            )
        for facet in (
            "value_status",
            "polarity",
            "degree",
            "certainty",
            "concept",
            "summary",
        ):
            if relations[facet] != "not_applicable":
                differences.append(
                    SemanticVerificationDifference(
                        proposition.proposition_id,
                        facet,
                        str(relations[facet]),
                        "mark_optional_proposition_omitted",
                    )
                )
        if getattr(item, "evidence_spans"):
            differences.append(
                SemanticVerificationDifference(
                    proposition.proposition_id,
                    "evidence",
                    "present_for_omitted_optional",
                    "clear_omitted_optional_evidence",
                )
            )

    @staticmethod
    def _validate_realized_proposition(
        proposition: SemanticProposition,
        item: object,
        differences: list[SemanticVerificationDifference],
    ) -> None:
        assert proposition.value is not None
        expected_relations: dict[str, str] = {
            "predicate": "preserved",
            "value_status": "preserved",
            "certainty": "preserved",
            "polarity": (
                "preserved" if proposition.value.polarity is not None else "not_applicable"
            ),
            "degree": (
                "preserved" if proposition.value.degree is not None else "not_applicable"
            ),
            "concept": "preserved" if proposition.concept is not None else "not_applicable",
            "summary": (
                "preserved" if proposition.summary_mode == "overview" else "not_applicable"
            ),
        }
        actual_relations = {
            "predicate": getattr(item, "predicate_relation"),
            "value_status": getattr(item, "value_status_relation"),
            "polarity": getattr(item, "polarity_relation"),
            "degree": getattr(item, "degree_relation"),
            "certainty": getattr(item, "certainty_relation"),
            "concept": getattr(item, "concept_relation"),
            "summary": getattr(item, "summary_relation"),
        }
        for facet, expected in expected_relations.items():
            actual = str(actual_relations[facet])
            if actual == expected:
                continue
            differences.append(
                SemanticVerificationDifference(
                    proposition.proposition_id,
                    facet,
                    actual,
                    CharacterSemanticVerificationPolicy._repair_for(
                        proposition,
                        facet,
                        actual,
                    ),
                )
            )

    @staticmethod
    def _repair_for(
        proposition: SemanticProposition,
        facet: str,
        relation: str,
    ) -> str:
        if proposition.realization_policy == "optional":
            if relation in {
                "omitted",
                "ambiguous",
                "changed",
                "unrelated",
                "contradicted",
                "weaker",
                "stronger",
                "committed_when_unknown",
                "unknown_when_known",
                "collapsed",
            }:
                return "restore_facet_or_drop_optional_proposition"
        repairs = {
            "predicate": "restore_required_predicate",
            "value_status": (
                "restore_unknown_status"
                if relation == "committed_when_unknown"
                else "restore_value_status"
            ),
            "polarity": "restore_polarity",
            "degree": "restore_degree",
            "certainty": (
                "reduce_epistemic_commitment"
                if relation == "stronger"
                else "increase_epistemic_commitment"
                if relation == "weaker"
                else "make_required_meaning_clearer"
            ),
            "concept": "restore_required_concept",
            "summary": "restore_overview_summary",
        }
        return repairs.get(facet, "make_required_meaning_clearer")
