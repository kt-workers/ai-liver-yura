from __future__ import annotations

from dataclasses import dataclass

from app.domain.contracts.common import require_identifier, require_revision


def _positive_int(value: int, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} は1以上の整数でなければなりません")
    return value


@dataclass(frozen=True, slots=True)
class InputBounds:
    max_text_codepoints: int
    max_payload_json_bytes: int
    max_session_metadata_json_bytes: int
    max_active_sessions_per_source: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_text_codepoints",
            "max_payload_json_bytes",
            "max_session_metadata_json_bytes",
            "max_active_sessions_per_source",
        ):
            _positive_int(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class ExecutiveBounds:
    max_source_event_refs: int
    max_fact_refs: int
    max_capability_descriptors: int
    max_precondition_facts: int
    max_candidate_intents: int
    max_goal_transitions: int
    max_commitment_transitions: int
    max_refs_per_intent: int
    max_fact_payload_json_bytes: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_source_event_refs",
            "max_fact_refs",
            "max_capability_descriptors",
            "max_precondition_facts",
            "max_candidate_intents",
            "max_goal_transitions",
            "max_commitment_transitions",
            "max_refs_per_intent",
            "max_fact_payload_json_bytes",
        ):
            _positive_int(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class GoalContextBounds:
    max_active_goals: int
    max_suspended_goals: int
    max_due_or_active_commitments: int
    max_recently_changed_items: int
    max_refs_per_goal: int
    max_refs_per_commitment: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_active_goals",
            "max_suspended_goals",
            "max_due_or_active_commitments",
            "max_recently_changed_items",
            "max_refs_per_goal",
            "max_refs_per_commitment",
        ):
            _positive_int(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class PlanningBounds:
    max_capability_descriptors: int
    max_planning_blockers: int
    max_activity_context_refs: int
    max_plan_steps: int
    max_dependencies_per_step: int
    max_precondition_refs_per_step: int
    max_completion_refs_per_step: int
    max_plan_completion_refs: int
    max_checkpoint_refs: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_capability_descriptors",
            "max_planning_blockers",
            "max_activity_context_refs",
            "max_plan_steps",
            "max_dependencies_per_step",
            "max_precondition_refs_per_step",
            "max_completion_refs_per_step",
            "max_plan_completion_refs",
            "max_checkpoint_refs",
        ):
            _positive_int(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class SpeechSemanticBounds:
    max_facts: int
    max_truth_constraints: int
    max_relationship_constraints: int
    max_discourse_constraints: int
    max_propositions: int
    max_evidence_refs_per_proposition: int
    max_constraint_refs_per_plan: int
    max_question_budget: int
    max_new_direction_budget: int
    max_fact_payload_json_bytes: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_facts",
            "max_truth_constraints",
            "max_relationship_constraints",
            "max_discourse_constraints",
            "max_propositions",
            "max_evidence_refs_per_proposition",
            "max_constraint_refs_per_plan",
            "max_question_budget",
            "max_new_direction_budget",
            "max_fact_payload_json_bytes",
        ):
            _positive_int(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class CharacterLanguageBounds:
    max_constraint_views: int
    max_confirmed_profile_facets: int
    max_segments: int
    max_segment_codepoints: int
    max_total_utterance_codepoints: int
    max_realization_refs_per_segment: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_constraint_views",
            "max_confirmed_profile_facets",
            "max_segments",
            "max_segment_codepoints",
            "max_total_utterance_codepoints",
            "max_realization_refs_per_segment",
        ):
            _positive_int(getattr(self, field_name), field_name)
        if self.max_total_utterance_codepoints < self.max_segment_codepoints:
            raise ValueError(
                "max_total_utterance_codepoints は max_segment_codepoints 以上でなければなりません"
            )


@dataclass(frozen=True, slots=True)
class SemanticVerificationBounds:
    max_blind_units: int
    max_evidence_refs_per_unit: int
    max_quote_codepoints: int
    max_interaction_acts_per_unit: int
    max_supporting_units_per_proposition: int
    max_proposition_relations: int
    max_accounting_entries: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_blind_units",
            "max_evidence_refs_per_unit",
            "max_quote_codepoints",
            "max_interaction_acts_per_unit",
            "max_supporting_units_per_proposition",
            "max_proposition_relations",
            "max_accounting_entries",
        ):
            _positive_int(getattr(self, field_name), field_name)
        if self.max_accounting_entries < self.max_blind_units:
            raise ValueError(
                "max_accounting_entries は max_blind_units 以上でなければなりません"
            )


@dataclass(frozen=True, slots=True)
class BrainOperationalBoundsPolicy:
    policy_id: str
    policy_revision: int
    input: InputBounds
    executive: ExecutiveBounds
    goal_context: GoalContextBounds
    planning: PlanningBounds
    speech_semantics: SpeechSemanticBounds
    character_language: CharacterLanguageBounds
    semantic_verification: SemanticVerificationBounds

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        typed_sections = (
            ("input", self.input, InputBounds),
            ("executive", self.executive, ExecutiveBounds),
            ("goal_context", self.goal_context, GoalContextBounds),
            ("planning", self.planning, PlanningBounds),
            ("speech_semantics", self.speech_semantics, SpeechSemanticBounds),
            ("character_language", self.character_language, CharacterLanguageBounds),
            (
                "semantic_verification",
                self.semantic_verification,
                SemanticVerificationBounds,
            ),
        )
        for field_name, value, expected_type in typed_sections:
            if not isinstance(value, expected_type):
                raise ValueError(f"{field_name} の型が不正です")
        if (
            self.semantic_verification.max_proposition_relations
            < self.speech_semantics.max_propositions
        ):
            raise ValueError(
                "Semantic VerificationはSpeech Semanticsの全propositionを収容できなければなりません"
            )
        if self.planning.max_capability_descriptors > self.executive.max_capability_descriptors:
            raise ValueError(
                "Planningのcapability上限はExecutiveの供給上限を超えられません"
            )


V2_BRAIN_OPERATIONAL_BOUNDS_POLICY = BrainOperationalBoundsPolicy(
    policy_id="v2.brain-operational-bounds.default",
    policy_revision=1,
    input=InputBounds(
        max_text_codepoints=32768,
        max_payload_json_bytes=262144,
        max_session_metadata_json_bytes=32768,
        max_active_sessions_per_source=64,
    ),
    executive=ExecutiveBounds(
        max_source_event_refs=64,
        max_fact_refs=256,
        max_capability_descriptors=128,
        max_precondition_facts=128,
        max_candidate_intents=16,
        max_goal_transitions=32,
        max_commitment_transitions=32,
        max_refs_per_intent=64,
        max_fact_payload_json_bytes=16384,
    ),
    goal_context=GoalContextBounds(
        max_active_goals=32,
        max_suspended_goals=32,
        max_due_or_active_commitments=64,
        max_recently_changed_items=64,
        max_refs_per_goal=64,
        max_refs_per_commitment=64,
    ),
    planning=PlanningBounds(
        max_capability_descriptors=128,
        max_planning_blockers=64,
        max_activity_context_refs=128,
        max_plan_steps=64,
        max_dependencies_per_step=16,
        max_precondition_refs_per_step=32,
        max_completion_refs_per_step=32,
        max_plan_completion_refs=64,
        max_checkpoint_refs=64,
    ),
    speech_semantics=SpeechSemanticBounds(
        max_facts=128,
        max_truth_constraints=128,
        max_relationship_constraints=64,
        max_discourse_constraints=64,
        max_propositions=64,
        max_evidence_refs_per_proposition=16,
        max_constraint_refs_per_plan=128,
        max_question_budget=16,
        max_new_direction_budget=16,
        max_fact_payload_json_bytes=16384,
    ),
    character_language=CharacterLanguageBounds(
        max_constraint_views=128,
        max_confirmed_profile_facets=128,
        max_segments=64,
        max_segment_codepoints=2048,
        max_total_utterance_codepoints=8192,
        max_realization_refs_per_segment=32,
    ),
    semantic_verification=SemanticVerificationBounds(
        max_blind_units=128,
        max_evidence_refs_per_unit=16,
        max_quote_codepoints=512,
        max_interaction_acts_per_unit=4,
        max_supporting_units_per_proposition=32,
        max_proposition_relations=64,
        max_accounting_entries=128,
    ),
)
