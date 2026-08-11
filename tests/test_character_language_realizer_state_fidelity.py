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


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やか",
        speaking_style="自然な日本語",
        streaming_style="会話相手へ自然に反応する",
    )


def _context(
    *,
    user_input: str,
    target_id: str,
    propositions: tuple[SemanticProposition, ...],
) -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", target_id),
        propositions=propositions,
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    return ResponseContext(
        user_input=user_input,
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="内部状態へ直接答える",
        speech_act="question",
        memory={"semantic_utterance_plan": plan.as_context()},
    )


def test_primary_explicit_intensity_requires_intensity_fidelity() -> None:
    context = _context(
        user_input="楽しい？",
        target_id="joy",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="joy",
                state="high",
                certainty="high",
                concept=None,
                evidence_refs=("emotion.current.reactive.joy",),
            ),
        ),
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=_profile(),
        correction=None,
    )

    assert '"state_semantics": "explicit_intensity_state"' in prompt
    assert '"state_fidelity": "preserve_exact_semantic_state"' in prompt
    assert '"intensity_fidelity": "must_preserve_intensity_if_realized"' in prompt
    assert "単なるpresentではなく明示的な強度state" in prompt
    assert "存在だけへ弱めず強度差を意味的に保持" in prompt


def test_unknown_forbids_yes_no_polarity_commitment() -> None:
    context = _context(
        user_input="悲しい？",
        target_id="sadness",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="sadness",
                state="unknown",
                certainty="low",
                concept=None,
                evidence_refs=(),
            ),
        ),
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=_profile(),
        correction=None,
    )

    assert '"state_semantics": "unknown_without_polarity_guess"' in prompt
    assert '"polarity_commitment": "forbidden"' in prompt
    assert "yes/no型の質問" in prompt
    assert "肯定・否定markerでpolarityを確定しない" in prompt


def test_supporting_proposition_is_optional_but_facet_complete_when_realized() -> None:
    context = _context(
        user_input="今どんな気分？",
        target_id="current_feeling",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_feeling",
                state="overview",
                certainty="high",
                concept=None,
                evidence_refs=("emotion.reactive",),
            ),
            SemanticProposition(
                kind="self_state_dimension",
                predicate="joy",
                state="high",
                certainty="high",
                concept=None,
                evidence_refs=("emotion.current.reactive.joy",),
            ),
            SemanticProposition(
                kind="self_state_dimension",
                predicate="calm",
                state="low",
                certainty="high",
                concept=None,
                evidence_refs=("emotion.current.reactive.calm",),
            ),
        ),
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=_profile(),
        correction=None,
    )

    assert '"realization_policy": "required"' in prompt
    assert '"realization_policy": "optional_but_facet_complete_if_realized"' in prompt
    assert '"if_realized_required_facets": ["predicate", "state", "certainty"]' in prompt
    assert prompt.count('"intensity_fidelity": "must_preserve_intensity_if_realized"') >= 2
    assert "supporting propositionは省略可能" in prompt
    assert "supporting stateの強度やcertaintyを落としたpartial realization" in prompt


def test_state_preserved_regeneration_feedback_requests_state_fidelity_repair() -> None:
    context = _context(
        user_input="悲しい？",
        target_id="sadness",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="sadness",
                state="unknown",
                certainty="high",
                concept=None,
                evidence_refs=("emotion.current.reactive.sadness",),
            ),
        ),
    )
    correction = json.dumps(
        {
            "reason": "semantic_facet_validation_failed",
            "claim_differences": ["state_preserved=false: unknownをpresentへ変換した"],
        },
        ensure_ascii=False,
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=_profile(),
        correction=correction,
    )

    assert '"restore_state_fidelity"' in prompt
    assert "Planのstateをpresenceだけへ弱めず" in prompt
    assert "unknownを肯定/否定へ変換せず" in prompt
    assert "採用したpropositionのstate意味をそのまま復元" in prompt


def test_state_fidelity_contract_does_not_expose_evidence_paths() -> None:
    context = _context(
        user_input="楽しい？",
        target_id="joy",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="joy",
                state="high",
                certainty="high",
                concept=None,
                evidence_refs=("emotion.current.reactive.joy",),
            ),
        ),
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=_profile(),
        correction=None,
    )

    assert "emotion.current.reactive.joy" not in prompt


# CI-only synchronize trigger for temporary Unit PR.
