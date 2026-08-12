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
from app.runtime.character_realization_validator import CharacterRealizationValidator


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


def _prompt() -> str:
    plan = _plan()
    return CharacterRealizationObserverPromptBuilder().build(
        _context(plan),
        _response(),
        plan,
    )


def test_observer_candidate_payload_does_not_expose_expected_semantic_facets() -> None:
    prompt = _prompt()
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
    prompt = _prompt()

    assert "期待state、期待certainty、期待conceptは与えられていない" in prompt
    assert "期待値を想像して合わせない" in prompt
    assert "自然言語の意味判定を有限個の単語・phrase・regex・substring対応表へ置き換えない" in prompt
    assert "semantic_realizations等の自己申告metadataは観測根拠にしない" in prompt


def test_observer_prompt_distinguishes_absence_intensity_overview_and_unknown() -> None:
    prompt = _prompt()

    assert "否定や非存在をlowへ読み替えない" in prompt
    assert "順序づけられた強度差" in prompt
    assert "overviewは対象そのものを単にpresentと述べる状態ではない" in prompt
    assert "全体状態・総合状態" in prompt
    assert "unknownは対象の存在・不在・強度・値を現時点で確定していない" in prompt


def test_observer_certainty_matches_semantic_proposition_certainty_including_unknown() -> None:
    prompt = _prompt()

    assert "観測器自身の判定自信度" in prompt
    assert "このpredicateはobserved_stateである" in prompt
    assert "Semantic Plan側のcertaintyも同じ命題certainty" in prompt
    assert "unknownだから自動的にcertainty=lowへ固定しない" in prompt
    assert "observed_certainty=highになり得る" in prompt


def test_observer_evidence_must_come_only_from_character_speech() -> None:
    prompt = _prompt()

    assert "User Wording Hintはevidenceではない" in prompt
    assert "Character Speechに実在する原文部分だけ" in prompt
    assert "User Wording Hint、Candidate ID、説明文をspanへ混ぜない" in prompt
    assert "top-levelは必ずobject" in prompt


def test_runtime_realization_validator_has_no_finite_degree_semantic_dictionary() -> None:
    source = inspect.getsource(character_realization_validator)

    for forbidden in (
        "_EXPLICIT_INTENSITY_MARKERS",
        "_explicit_intensity_markers",
        "_has_explicit_degree_evidence",
        "_deterministic_surface_differences",
    ):
        assert forbidden not in source


def test_runtime_post_observation_validator_does_not_revalidate_state_fidelity() -> None:
    downstream_source = inspect.getsource(
        CharacterRealizationValidator._accepted_post_observation_differences
    )
    observer_source = inspect.getsource(CharacterRealizationValidator._observation_differences)

    for removed_post_observation_field in (
        "state_fidelity",
        "intensity_semantics_preserved",
        "presence_only_counterfactual_equivalent",
        "intensity_evidence_spans",
        "certainty_evidence_spans",
        "state_preserved",
        "certainty_preserved",
    ):
        assert removed_post_observation_field not in downstream_source

    assert "observation.observed_state" in observer_source
    assert "observation.observed_certainty" in observer_source
    assert "observation.state_evidence_spans" in observer_source
    assert "observation.certainty_evidence_spans" in observer_source
