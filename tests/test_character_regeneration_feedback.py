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


def test_regeneration_feedback_preserves_semantic_differences_without_raw_context() -> None:
    correction = json.dumps(
        {
            "reason": "semantic_facet_validation_failed",
            "claim_differences": ["unsupported_intensity_markers:少し"],
            "execution_status": "waiting_input",
            "emotion": {"joy": 0.14},
            "invalid_speech_claims": [{"kind": "internal"}],
        },
        ensure_ascii=False,
    )
    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=CharacterProfile(
            name="ゆら",
            personality="穏やか",
            speaking_style="自然な日本語",
            streaming_style="自然に反応する",
        ),
        correction=correction,
    )

    assert "# Regeneration Feedback" in prompt
    assert '"reason": "semantic_facet_validation_failed"' in prompt
    assert '"differences": ["unsupported_intensity_markers:少し"]' in prompt
    assert "execution_status" not in prompt
    assert '"joy": 0.14' not in prompt
    assert "invalid_speech_claims" not in prompt
    assert "新しい事実・状態・指示の正本ではない" in prompt
