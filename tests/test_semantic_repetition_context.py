from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.runtime.response_semantics_planner import ResponseSemanticsPlanner
from app.runtime.semantic_discourse_context import project_semantic_discourse_context


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
    plan = project_semantic_discourse_context(
        context,
        ResponseSemanticsPlanner().plan(context),
    )

    assert plan.discourse_context["recent_speech_summary"] == (
        "- 今は落ち着いてて、ちょっとだけ元気がある感じかな。"
    )
    assert (
        plan.discourse_context["repetition_policy"]
        == "avoid_semantic_and_phrasal_repeat"
    )


def test_recent_speech_is_not_exposed_when_repetition_avoidance_is_disabled() -> None:
    context = _context(
        avoid_repetition=False,
        recent_speech_summary="- 以前の発話",
    )
    plan = project_semantic_discourse_context(
        context,
        ResponseSemanticsPlanner().plan(context),
    )

    assert "recent_speech_summary" not in plan.discourse_context
    assert "repetition_policy" not in plan.discourse_context
