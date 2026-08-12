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


def test_unknown_state_is_not_permission_to_guess_target_presence() -> None:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "current_desire"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_desire",
                state="unknown",
                certainty="low",
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    context = ResponseContext(
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
    profile = CharacterProfile(
        name="ゆら",
        personality="穏やか",
        speaking_style="自然な日本語",
        streaming_style="会話相手へ自然に反応する",
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=profile,
        correction=None,
    )

    assert '"state": "unknown"' in prompt
    assert '"certainty": "low"' in prompt
    assert "unknownをpresent/absent/low等へ変換せず" in prompt
    assert "特定polarityを推測しない" in prompt
    assert "別のstateや強度を推測してよい許可ではない" in prompt
