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
from app.runtime.character_language_realizer_service import CharacterLanguageRealizerService


def _high_joy_context() -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "joy"),
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
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    return ResponseContext(
        user_input="楽しい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の楽しさへ直接答える",
        speech_act="question",
        memory={"semantic_utterance_plan": plan.as_context()},
    )


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やか",
        speaking_style="自然な日本語",
        streaming_style="自然に反応する",
    )


def test_e1_overstated_intensity_is_normalized_to_state_fidelity_repair() -> None:
    correction = json.dumps(
        {
            "reason": "state_intensity_overstated",
            "claim_differences": [
                "'かなり' が plan の high を超える強い程度表現として追加され、state fidelity が exact ではありません"
            ],
        },
        ensure_ascii=False,
    )

    normalized = CharacterLanguageRealizerService._normalize_state_fidelity_correction(
        correction
    )
    assert normalized is not None
    normalized_value = json.loads(normalized)
    assert any(
        "state_preserved=false" in item
        for item in normalized_value["claim_differences"]
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _high_joy_context(),
        character_profile=_profile(),
        correction=normalized,
    )

    assert '"restore_state_fidelity"' in prompt
    assert '"state": "high"' in prompt
    assert '"state_fidelity": "preserve_exact_semantic_state"' in prompt
    assert "Planのstateをpresenceだけへ弱めず" in prompt
    assert "存在だけへ弱めず強度差を意味的に保持" in prompt
    assert "emotion.current.reactive.joy" not in prompt


def test_structured_state_fidelity_relation_is_normalized() -> None:
    for diagnostic in (
        "proposition:0:joy:state_fidelity:strengthened",
        "proposition:0:joy:state_fidelity:weakened",
        "proposition:0:sadness:state_fidelity:unknown_committed",
        "proposition:0:sadness:state_fidelity:polarity_changed",
    ):
        correction = json.dumps(
            {
                "reason": "semantic_facet_validation_failed",
                "claim_differences": [diagnostic],
            },
            ensure_ascii=False,
        )
        normalized = CharacterLanguageRealizerService._normalize_state_fidelity_correction(
            correction
        )
        assert normalized is not None
        value = json.loads(normalized)
        assert any(
            "state_preserved=false" in item for item in value["claim_differences"]
        )


def test_unrelated_regeneration_feedback_is_not_rewritten() -> None:
    correction = json.dumps(
        {
            "reason": "recent_speech_too_similar",
            "claim_differences": ["semantic_novelty_required"],
        },
        ensure_ascii=False,
    )

    normalized = CharacterLanguageRealizerService._normalize_state_fidelity_correction(
        correction
    )

    assert normalized == correction
