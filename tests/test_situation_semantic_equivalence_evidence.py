from __future__ import annotations

import json

import pytest

from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    BehaviorPlanningContext,
    SituationAnalysis,
)
from app.domain.morals import (
    ActivityCandidateSemanticEquivalenceEvidence,
    ExecutionBoundaryEquivalenceStatus,
    MoralProfile,
    MoralState,
    SemanticEquivalenceDimension,
    SemanticEquivalenceStatus,
)
from app.runtime.situation_evaluator import SituationEvaluator
from app.runtime.situation_semantic_equivalence_shadow_observer import (
    SituationSemanticEquivalenceShadowObserver,
)


def _definition(activity_type: str) -> ActivityDefinition:
    return ActivityDefinition(
        activity_type=activity_type,
        display_name=activity_type,
        required_capability=None,
        provider_plugin_id="runtime",
        description=f"{activity_type}を行う",
        supported_operations=(ActivityOperation.START,),
        constraints_schema={"type": "object", "additionalProperties": False},
    )


def _raw_response(*, confidence: float = 0.95) -> str:
    return json.dumps(
        {
            "decision": "start_activity",
            "activity_type": "conversation_with_user",
            "operation": "start",
            "goal": "ユーザーと対話する",
            "constraints": {},
            "speech_act": "statement",
            "conversation_phase": "active",
            "initiative_level": 0.4,
            "negated": False,
            "hypothetical": False,
            "past_reference": False,
            "knowledge_question": False,
            "confidence": confidence,
            "reason": "semantic_match",
            "ongoing_input_decision": None,
            "semantic_equivalence": {
                "candidate_group": [
                    "autonomous_talk",
                    "conversation_with_user",
                ],
                "intent": "confirmed",
                "operation": "confirmed",
                "goal": "confirmed",
                "reasons": ["same_conversational_goal"],
                "source": "untrusted_model_value",
                "evidence_id": "untrusted_model_id",
            },
        },
        ensure_ascii=False,
    )


class _Model:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    async def evaluate(self, activity: object) -> str:
        del activity
        return self.raw


class _PromptBuilder:
    def build(self, context: BehaviorPlanningContext) -> str:
        del context
        return "semantic evidence prompt"


class _RecordingObserver:
    def __init__(self) -> None:
        self.calls: list[tuple[BehaviorPlanningContext, SituationAnalysis]] = []

    def observe(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> None:
        self.calls.append((context, analysis))


def _definitions() -> tuple[ActivityDefinition, ...]:
    return (
        _definition("autonomous_talk"),
        _definition("conversation_with_user"),
    )


def _planning_context() -> BehaviorPlanningContext:
    return BehaviorPlanningContext(
        user_text="どちらかの方法で会話を続けて",
        source_event_id="event-semantic-evidence-1",
        available_capabilities=frozenset(),
        activity_definitions=_definitions(),
    )


def test_parse_creates_typed_evidence_with_runtime_provenance() -> None:
    evaluator = SituationEvaluator(_Model(""), prompt_builder=_PromptBuilder())

    analysis = evaluator.parse(
        _raw_response(),
        _definitions(),
        semantic_evidence_source="situation_evaluator_llm",
        semantic_evidence_id="runtime-evidence-1",
    )

    assert analysis is not None
    evidence = analysis.semantic_equivalence_evidence
    assert evidence is not None
    assert evidence.candidate_group == (
        "autonomous_talk",
        "conversation_with_user",
    )
    assert evidence.intent is SemanticEquivalenceDimension.CONFIRMED
    assert evidence.operation is SemanticEquivalenceDimension.CONFIRMED
    assert evidence.goal is SemanticEquivalenceDimension.CONFIRMED
    assert evidence.source == "situation_evaluator_llm"
    assert evidence.evidence_id == "runtime-evidence-1"
    assert evidence.source != "untrusted_model_value"
    assert evidence.evidence_id != "untrusted_model_id"


def test_parse_does_not_trust_evidence_without_runtime_provenance() -> None:
    evaluator = SituationEvaluator(_Model(""), prompt_builder=_PromptBuilder())

    analysis = evaluator.parse(_raw_response(), _definitions())

    assert analysis is not None
    assert analysis.semantic_equivalence_evidence is None


def test_parse_discards_unknown_candidate_group() -> None:
    payload = json.loads(_raw_response())
    payload["semantic_equivalence"]["candidate_group"] = [
        "autonomous_talk",
        "unknown_activity",
    ]
    evaluator = SituationEvaluator(_Model(""), prompt_builder=_PromptBuilder())

    analysis = evaluator.parse(
        json.dumps(payload, ensure_ascii=False),
        _definitions(),
        semantic_evidence_source="situation_evaluator_llm",
        semantic_evidence_id="runtime-evidence-2",
    )

    assert analysis is not None
    assert analysis.semantic_equivalence_evidence is None


@pytest.mark.asyncio
async def test_high_confidence_evidence_is_forwarded_to_shadow_observer() -> None:
    observer = _RecordingObserver()
    evaluator = SituationEvaluator(
        _Model(_raw_response(confidence=0.95)),
        prompt_builder=_PromptBuilder(),
        semantic_equivalence_shadow_observer=observer,
    )

    analysis = await evaluator.evaluate(_planning_context())

    assert analysis.semantic_equivalence_evidence is not None
    assert analysis.semantic_equivalence_evidence.evidence_id == (
        "event-semantic-evidence-1:semantic-equivalence:1"
    )
    assert len(observer.calls) == 1
    assert observer.calls[0][1] is analysis


@pytest.mark.asyncio
async def test_low_confidence_evidence_is_discarded_before_shadow() -> None:
    observer = _RecordingObserver()
    evaluator = SituationEvaluator(
        _Model(_raw_response(confidence=0.40)),
        prompt_builder=_PromptBuilder(),
        semantic_equivalence_shadow_observer=observer,
    )

    analysis = await evaluator.evaluate(_planning_context())

    assert analysis.reason == "semantic_confidence_below_threshold"
    assert analysis.semantic_equivalence_evidence is None
    assert observer.calls == []


def test_shadow_observer_confirms_evidence_without_activating_preference() -> None:
    profile = MoralProfile(compassion=1.0, altruism=1.0, dominance=0.0)
    state = MoralState(
        empathy_activation=1.0,
        selfish_impulse=0.0,
        aggressive_impulse=0.0,
    )
    context = BehaviorPlanningContext(
        user_text="会話を続けて",
        source_event_id="event-semantic-shadow-1",
        available_capabilities=frozenset(),
        activity_definitions=_definitions(),
        motivation={"recommended_activity_types": []},
        moral={
            "profile": profile.as_dict(),
            "state": state.as_dict(),
            "composite": profile.compose(state).as_dict(),
            "observation_only": True,
        },
    )
    evidence = ActivityCandidateSemanticEquivalenceEvidence(
        candidate_group=(
            "autonomous_talk",
            "conversation_with_user",
        ),
        intent=SemanticEquivalenceDimension.CONFIRMED,
        operation=SemanticEquivalenceDimension.CONFIRMED,
        goal=SemanticEquivalenceDimension.CONFIRMED,
        source="situation_evaluator_llm",
        evidence_id="runtime-evidence-3",
    )
    analysis = SituationAnalysis(
        activity_candidate="conversation_with_user",
        operation=ActivityOperation.START,
        goal="ユーザーと対話する",
        evaluator_type="llm",
        semantic_equivalence_evidence=evidence,
    )

    result = SituationSemanticEquivalenceShadowObserver().observe(
        context,
        analysis,
    )

    assert result.semantic_equivalence.status is SemanticEquivalenceStatus.CONFIRMED
    assert result.semantic_equivalence.evidence_id == "runtime-evidence-3"
    assert result.execution_boundary_equivalence.status is (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    assert result.execution_boundary_equivalence.capability.status is (
        ExecutionBoundaryEquivalenceStatus.CONFIRMED
    )
    assert result.execution_boundary_equivalence.constraint.status is (
        ExecutionBoundaryEquivalenceStatus.CONFIRMED
    )
    assert result.execution_boundary_equivalence.authority.status is (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    assert result.execution_boundary_equivalence.safety.status is (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    assert result.activation_permitted is False
    assert result.current_order == (
        "autonomous_talk",
        "conversation_with_user",
    )
    assert result.hypothetical_order == (
        "conversation_with_user",
        "autonomous_talk",
    )
