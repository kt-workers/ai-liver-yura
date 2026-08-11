from __future__ import annotations

import inspect
import json

from app.adapters.prompt.character_realization_observer_prompt_builder import (
    CharacterRealizationObserverPromptBuilder,
)
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.domain.character_utterance import LinguisticPerformance
from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticTarget,
    SemanticUtterancePlan,
)
from app.runtime import character_realization_validator


def _plan() -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "energy"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="energy",
                state="low",
                certainty="medium",
                concept="vitality",
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )


def _context(plan: SemanticUtterancePlan) -> ResponseContext:
    return ResponseContext(
        user_input="今の元気はどんな感じ？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の状態へ直接答える",
        speech_act="question",
        memory={"semantic_utterance_plan": plan.as_context()},
    )


def _response() -> CharacterResponse:
    speech = "元気は控えめな感じかな。"
    return CharacterResponse(
        speech=speech,
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(phrasing=(speech,)),
        semantic_realizations=("proposition:0:energy",),
    )


def test_observer_candidate_payload_does_not_expose_expected_semantic_facets() -> None:
    plan = _plan()
    prompt = CharacterRealizationObserverPromptBuilder().build(
        _context(plan),
        _response(),
        plan,
    )
    lines = prompt.splitlines()
    marker = lines.index("# Candidate Predicate IDs")
    candidates = json.loads(lines[marker + 1])

    assert candidates == [
        {
            "realization_id": "proposition:0:energy",
            "kind": "self_state",
            "predicate": "energy",
        }
    ]
    assert "state" not in candidates[0]
    assert "certainty" not in candidates[0]
    assert "concept" not in candidates[0]


def test_observer_prompt_explicitly_forbids_plan_anchored_state_inference() -> None:
    plan = _plan()
    prompt = CharacterRealizationObserverPromptBuilder().build(
        _context(plan),
        _response(),
        plan,
    )

    assert "期待state、期待certainty、期待conceptは与えられていない" in prompt
    assert "期待値を想像して合わせない" in prompt
    assert "有限個の語彙リストへ置き換えて判定しない" in prompt
    assert "semantic_realizations等の自己申告metadataは観測根拠にしない" in prompt


def test_runtime_realization_validator_has_no_finite_degree_semantic_dictionary() -> None:
    source = inspect.getsource(character_realization_validator)

    for forbidden in (
        "_EXPLICIT_INTENSITY_MARKERS",
        "_explicit_intensity_markers",
        "_has_explicit_degree_evidence",
        "_deterministic_surface_differences",
    ):
        assert forbidden not in source
