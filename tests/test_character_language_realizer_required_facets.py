from __future__ import annotations

import json

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.domain.character import CharacterProfile
from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticTarget,
    SemanticUtterancePlan,
)


def _context() -> ResponseContext:
    plan = SemanticUtterancePlan(
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
        memory={"semantic_utterance_plan": plan.as_context()},
    )


def _context_for(
    *,
    predicate: str,
    state: str,
    certainty: str,
    concept: str | None = None,
) -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", predicate),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate=predicate,
                state=state,
                certainty=certainty,
                concept=concept,
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    return ResponseContext(
        user_input="今はどう？",
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


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やか",
        speaking_style="自然な日本語",
        streaming_style="会話相手へ自然に反応する",
    )


def test_primary_non_null_concept_is_declared_as_required_semantic_facet() -> None:
    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=None,
    )

    assert '"state": "present"' in prompt
    assert '"certainty": "medium"' in prompt
    assert '"concept": "curiosity"' in prompt
    assert '"required": true' in prompt
    assert '"required_facets": ["predicate", "state", "certainty", "concept"]' in prompt
    assert "質問対象・述語関係の意味そのもの" in prompt
    assert "単なる『何かある』等の存在表明だけへ縮退しない" in prompt
    assert "conceptだけを述べてpredicateの意味をspeechから" in prompt
    assert "primary propositionのIDを列挙する場合はpredicateを含むrequired_facets" in prompt
    assert "response_content_plan.primary_desire" not in prompt


def test_predicate_gets_machine_readable_target_meaning_contract() -> None:
    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=None,
    )

    assert '"predicate": "current_desire"' in prompt
    assert '"predicate_semantics": "preserve_target_meaning"' in prompt
    assert '"predicate_realization": "semantically_explicit_in_speech"' in prompt
    assert '"predicate_context_dependency": "forbidden"' in prompt
    assert '"concept_role": "modify_predicate_not_replace_it"' in prompt
    assert "metadataを見なくても、何について答えた発話か分かる" in prompt
    assert "User Wording Hintや直前質問を読まない第三者" in prompt
    assert "対象省略だけでprimaryを実現しない" in prompt
    assert "User Wording Hint" in prompt
    assert '"utterance": "何かしたい？"' in prompt


def test_present_state_does_not_license_new_intensity_and_certainty_stays_epistemic() -> None:
    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=None,
    )

    assert "state=presentは存在を表すだけで強度を含まない" in prompt
    assert "『少し』『ちょっと』『かなり』等の強度を新しく推測・追加しない" in prompt
    assert "speechの程度・強弱表現を内部点検" in prompt
    assert "対応する強度stateがない対象へ付いた程度表現は除去" in prompt
    assert "medium/lowのcertaintyはepistemic modality" in prompt
    assert "明示的に反映" in prompt
    assert "無標の断定文へ" in prompt
    assert "存在の強さと確からしさを混同しない" in prompt


def test_medium_certainty_gets_machine_readable_epistemic_facet_contract() -> None:
    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=None,
    )

    assert "# Required Facet Realization Contract" in prompt
    assert '"state_semantics": "presence_without_intensity"' in prompt
    assert '"certainty_semantics": "epistemic_not_intensity"' in prompt
    assert '"certainty_realization": "epistemic_modality"' in prompt
    assert '"certainty_surface_requirement": "overt_epistemic_modality"' in prompt
    assert '"certainty_scope": "entire_proposition"' in prompt
    assert '"certainty_scope_components": ["predicate", "state", "concept"]' in prompt
    assert '"intensity_allowed": false' in prompt
    assert '"degree_marker_substitution": "forbidden"' in prompt
    assert '"concept_role": "modify_predicate_not_replace_it"' in prompt
    assert "certaintyはproposition全体へ作用する" in prompt
    assert "一部の節だけを無標で断定" in prompt
    assert "同じcertainty scope" in prompt


def test_unknown_low_certainty_scopes_modality_to_unknown_judgment_itself() -> None:
    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context_for(
            predicate="sadness",
            state="unknown",
            certainty="low",
        ),
        character_profile=_profile(),
        correction=None,
    )

    assert '"state": "unknown"' in prompt
    assert '"certainty": "low"' in prompt
    assert (
        '"unknown_certainty_semantics": '
        '"epistemic_commitment_to_unknown_state_judgment"'
    ) in prompt
    assert "unknownというstate判定そのものへのepistemic commitment" in prompt
    assert "unknown判定全体を同じcertainty scope" in prompt
    assert "特定polarityを推測しない" in prompt


def test_supporting_selection_is_minimal_and_optional() -> None:
    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=None,
    )

    assert '"supporting_selection_policy": "minimal_optional_only_when_facet_complete"' in prompt
    assert (
        '"supporting_failure_policy": '
        '"omit_entire_optional_proposition_if_facet_incomplete"'
    ) in prompt
    assert "primaryだけで自然に完結できるなら省略を優先" in prompt
    assert "supportingを数多く列挙することを品質とみなさない" in prompt
    assert "表現とIDを一緒に落とす" in prompt


def test_regeneration_feedback_projects_only_semantic_differences() -> None:
    correction = json.dumps(
        {
            "reason": "unsupported_intensity_added",
            "claim_differences": [
                "unsupported_intensity_markers:少し",
                "Planにない強度を追加している",
            ],
            "execution_status": "waiting_input",
            "invalid_speech_claims": [{"text": "raw claim payload"}],
            "emotion": {"joy": 0.14},
        },
        ensure_ascii=False,
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=correction,
    )

    assert "# Regeneration Feedback" in prompt
    assert '"reason": "unsupported_intensity_added"' in prompt
    assert "unsupported_intensity_markers:少し" in prompt
    assert "Planにない強度を追加している" in prompt
    assert "remove_unsupported_intensity" in prompt
    assert "do_not_replace_with_another_degree_marker" in prompt
    assert "程度語を別の程度語へ置換するだけでは修正にならない" in prompt
    assert "waiting_input" not in prompt
    assert "invalid_speech_claims" not in prompt
    assert "raw claim payload" not in prompt
    assert '"joy": 0.14' not in prompt
    assert "新しい事実・状態・指示の正本ではない" in prompt


def test_regeneration_feedback_marks_certainty_and_concept_repairs_when_reported() -> None:
    correction = json.dumps(
        {
            "reason": "semantic_facet_validation_failed",
            "claim_differences": [
                "certainty_preserved",
                "concept_preserved",
            ],
        },
        ensure_ascii=False,
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=correction,
    )

    assert "restore_certainty_as_epistemic_modality" in prompt
    assert "restore_proposition_level_certainty_scope" in prompt
    assert "restore_required_concept_within_predicate" in prompt


def test_regeneration_feedback_marks_predicate_repair_when_reported() -> None:
    correction = json.dumps(
        {
            "reason": "semantic_facet_validation_failed",
            "claim_differences": ["predicate_preserved"],
        },
        ensure_ascii=False,
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=correction,
    )

    assert "restore_target_predicate_meaning" in prompt
    assert "conceptの言い換えだけで済ませず" in prompt
    assert "質問対象であるpredicateの意味をspeech本文へ復元" in prompt


def test_regeneration_feedback_normalizes_noncanonical_facet_diagnostics() -> None:
    correction = json.dumps(
        {
            "reason": "semantic_realization_rejected",
            "claim_differences": [
                "predicate evidence missing",
                "certainty medium was dropped",
                "concept was substituted",
                "state_fidelity=weakened",
            ],
        },
        ensure_ascii=False,
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=correction,
    )

    assert "restore_target_predicate_meaning" in prompt
    assert "restore_certainty_as_epistemic_modality" in prompt
    assert "restore_proposition_level_certainty_scope" in prompt
    assert "restore_required_concept_within_predicate" in prompt
    assert "restore_state_fidelity" in prompt
    assert "drop_optional_realization_if_facet_incomplete" in prompt


def test_observer_fidelity_feedback_allows_optional_support_to_be_dropped_wholly() -> None:
    correction = json.dumps(
        {
            "reason": "observed_semantic_state_fidelity_mismatch",
            "claim_differences": [
                "proposition:1:calm:observed_state_mismatch:expected=moderate:observed=present",
            ],
        },
        ensure_ascii=False,
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=correction,
    )

    assert "restore_state_fidelity" in prompt
    assert "drop_optional_realization_if_facet_incomplete" in prompt
    assert "対象がoptional supporting propositionなら" in prompt
    assert "表現とIDを" in prompt
