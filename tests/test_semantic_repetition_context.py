from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.runtime.internal_state_response_context import InternalStateAwareResponseContextBuilder
from app.runtime.response_semantics_planner import ResponseSemanticsPlanner


def _context(*, avoid_repetition: bool, recent_speech_summary: str) -> ResponseContext:
    return ResponseContext(
        user_input="今どんな気分？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の気分へ直接答える",
        speech_act="question",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.18,
                    "amusement": 0.08,
                    "calm": 0.64,
                    "anger": 0.0,
                }
            }
        },
        constraints={
            "avoid_repetition": avoid_repetition,
            "_internal_directive": {
                "structured_input_meaning": {
                    "input_speech_act": "question",
                    "expected_response": "direct_answer",
                    "target": {"type": "internal_state", "id": "current_feeling"},
                },
                "internal_directive": {
                    "response_mode": "answer",
                    "question_budget": 0,
                    "new_direction_budget": 0,
                    "self_disclosure_level": 0.35,
                },
            },
        },
        recent_speech_summary=recent_speech_summary,
    )


def test_recent_speech_is_projected_only_for_repetition_avoidance() -> None:
    context = _context(
        avoid_repetition=True,
        recent_speech_summary="- 今は落ち着いてて、ちょっとだけ元気がある感じかな。",
    )
    plan = ResponseSemanticsPlanner().plan(context)

    enriched = InternalStateAwareResponseContextBuilder._attach_repetition_context(
        context,
        plan,
    )

    assert enriched.discourse_context["recent_speech_summary"] == (
        "- 今は落ち着いてて、ちょっとだけ元気がある感じかな。"
    )
    assert (
        enriched.discourse_context["repetition_policy"]
        == "avoid_semantic_and_phrasal_repeat"
    )


def test_recent_speech_is_not_exposed_when_repetition_avoidance_is_disabled() -> None:
    context = _context(
        avoid_repetition=False,
        recent_speech_summary="- 以前の発話",
    )
    plan = ResponseSemanticsPlanner().plan(context)

    enriched = InternalStateAwareResponseContextBuilder._attach_repetition_context(
        context,
        plan,
    )

    assert "recent_speech_summary" not in enriched.discourse_context
    assert "repetition_policy" not in enriched.discourse_context
