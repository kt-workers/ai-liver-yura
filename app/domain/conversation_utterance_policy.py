from __future__ import annotations

from dataclasses import replace

from app.domain.response_content_plan import ResponseContentPlan


_QUESTION_STRATEGIES = frozenset(
    {"ask_follow_up", "ask_for_detail", "seek_clarification"}
)
_NEW_DIRECTION_STRATEGIES = frozenset(
    {
        "explore_related_topic",
        "propose_direction",
        "take_initiative",
        "define_next_step",
    }
)
_LOW_INITIATIVE_GREETING_STRATEGIES = frozenset(
    {
        "acknowledge_other",
        "continue_conversation",
        "observe_before_speaking",
        "share_reaction",
    }
)


def constrain_response_content_plan(
    plan: ResponseContentPlan,
    *,
    speech_act: str,
    conversation_phase: str,
    initiative_level: float,
) -> ResponseContentPlan:
    """確定済みの対話方針に合わせて発話表現Planを保守的に縮退する。"""

    normalized_speech_act = speech_act.strip().lower()
    normalized_phase = conversation_phase.strip().lower()
    low_initiative = initiative_level <= 0.25
    greeting = (
        normalized_speech_act == "greeting"
        or normalized_phase == "greeting"
    )

    if greeting and low_initiative:
        strategies = tuple(
            item
            for item in plan.conversation_strategies
            if item in _LOW_INITIATIVE_GREETING_STRATEGIES
        )
        if "acknowledge_other" not in strategies:
            strategies = ("acknowledge_other", *strategies)
        strategies = tuple(dict.fromkeys(strategies))[:3]
        return replace(
            plan,
            conversation_strategies=strategies,
            self_disclosure_level="none",
            question_budget=0,
            new_direction_budget=0,
            reasons=tuple(
                dict.fromkeys(
                    (
                        *plan.reasons,
                        "low_initiative_greeting_constrained",
                    )
                )
            ),
        )

    if low_initiative:
        strategies = tuple(
            item
            for item in plan.conversation_strategies
            if item not in _QUESTION_STRATEGIES
            and item not in _NEW_DIRECTION_STRATEGIES
        )
        return replace(
            plan,
            conversation_strategies=strategies or ("continue_conversation",),
            question_budget=0,
            new_direction_budget=0,
            reasons=tuple(
                dict.fromkeys(
                    (
                        *plan.reasons,
                        "low_initiative_response_constrained",
                    )
                )
            ),
        )

    return plan
