from __future__ import annotations

import json

from app.adapters.prompt.character_realization_observer_prompt_builder import (
    CharacterRealizationObserverPromptBuilder,
)
from app.adapters.prompt.character_realization_validator_prompt_builder import (
    CharacterRealizationValidatorPromptBuilder,
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


def _plan() -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "current_desire"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_desire",
                state="present",
                certainty="medium",
                concept="curiosity",
                evidence_refs=("response_content_plan.primary_desire",),
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )


def _context() -> ResponseContext:
    plan = _plan()
    return ResponseContext(
        user_input="何かしたい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の欲求へ直接答える",
        speech_act="question",
        memory={
            "semantic_utterance_plan": plan.as_context(),
            "semantic_validation": {
                "accepted": True,
                "reason": "semantic_plan_consistent",
                "differences": [],
            },
        },
    )


def _response() -> CharacterResponse:
    return CharacterResponse(
        speech="たぶん、何か知りたい気持ちはあるよ。",
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(
            phrasing=("たぶん", "何か知りたい気持ちはあるよ"),
            emphasis=("知りたい",),
            delivery_tags=("gentle",),
        ),
        semantic_realizations=("proposition:0:current_desire",),
    )


def _json_section(prompt: str, heading: str, next_heading: str) -> dict[str, object]:
    section = prompt.split(f"{heading}\n", 1)[1].split(f"\n{next_heading}", 1)[0]
    value = json.loads(section)
    assert isinstance(value, dict)
    return value


def _output_schema_example(prompt: str) -> dict[str, object]:
    value = json.loads(prompt.rsplit("JSONのみ返す:\n", 1)[1])
    assert isinstance(value, dict)
    return value


def test_required_facets_are_split_between_observer_and_post_observation_validator() -> None:
    plan = _plan()
    context = _context()
    response = _response()

    observer_prompt = CharacterRealizationObserverPromptBuilder().build(
        context,
        response,
        plan,
    )
    lines = observer_prompt.splitlines()
    marker = lines.index("# Candidate Predicate IDs")
    candidates = json.loads(lines[marker + 1])
    assert candidates == [
        {
            "realization_id": "proposition:0:current_desire",
            "kind": "self_state",
            "predicate": "current_desire",
        }
    ]
    assert "state" not in candidates[0]
    assert "certainty" not in candidates[0]
    assert "concept" not in candidates[0]
    assert "observed_state" in observer_prompt
    assert "observed_certainty" in observer_prompt

    validator_prompt = CharacterRealizationValidatorPromptBuilder().build(
        context,
        response,
    )
    contract = _json_section(
        validator_prompt,
        "# Post-Observation Semantic Contract",
        "# User Wording Hint",
    )
    propositions = contract["propositions"]
    assert isinstance(propositions, list)
    primary = propositions[0]
    assert isinstance(primary, dict)
    assert primary["required"] is True
    assert primary["predicate"] == "current_desire"
    assert primary["concept"] == "curiosity"
    assert "state" not in primary
    assert "certainty" not in primary
    assert "response_content_plan.primary_desire" not in validator_prompt


def test_post_observation_schema_validates_predicate_and_concept_without_revalidating_state() -> None:
    prompt = CharacterRealizationValidatorPromptBuilder().build(
        _context(),
        _response(),
    )

    utterance_view = _json_section(
        prompt,
        "# Character Utterance",
        "# Existence Boundaries",
    )
    assert utterance_view["semantic_realizations"] == [
        "proposition:0:current_desire"
    ]

    output_schema = _output_schema_example(prompt)
    semantic_checks = output_schema["semantic_checks"]
    assert isinstance(semantic_checks, dict)
    assert set(semantic_checks) == {
        "required_content_preserved",
        "forbidden_additions_absent",
        "unsupported_new_fact_absent",
        "existence_boundary_preserved",
        "budget_preserved",
    }

    proposition_checks = output_schema["realized_proposition_checks"]
    assert isinstance(proposition_checks, list)
    check = proposition_checks[0]
    assert isinstance(check, dict)
    assert set(check) == {
        "realization_id",
        "predicate_preserved",
        "predicate_evidence_spans",
        "concept_preserved",
        "concept_evidence_spans",
    }
    for removed in (
        "state_fidelity",
        "state_preserved",
        "certainty_preserved",
        "certainty_evidence_spans",
        "intensity_evidence_spans",
    ):
        assert removed not in check
