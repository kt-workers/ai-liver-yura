from unittest.mock import MagicMock

from app.domain.behavior import BehaviorPlanningContext, SituationAnalysis
from app.runtime.behavior_planner import BehaviorPlanner


def test_motivation_is_read_only_and_does_not_change_activity_plan() -> None:
    planner = BehaviorPlanner(situation_evaluator=MagicMock())
    analysis = SituationAnalysis(
        activity_candidate="conversation",
        operation=None,
        goal="通常会話を続ける",
        reason="normal_conversation",
        evaluator_type="deterministic",
    )
    without_motivation = BehaviorPlanningContext(
        user_text="こんにちは",
        source_event_id="event-1",
        available_capabilities=frozenset(),
    )
    with_motivation = BehaviorPlanningContext(
        user_text="こんにちは",
        source_event_id="event-1",
        available_capabilities=frozenset(),
        motivation={
            "primary_desire": "connection",
            "recommended_activity_types": ["conversation_with_user"],
            "recommended_conversation_strategies": ["ask_follow_up"],
            "moral_evaluation_available": False,
        },
    )

    baseline = planner.plan_from_analysis(without_motivation, analysis)
    observed = planner.plan_from_analysis(with_motivation, analysis)

    assert observed.decision == baseline.decision
    assert observed.activity_type == baseline.activity_type
    assert observed.goal == baseline.goal
    assert observed.operation == baseline.operation
    assert observed.constraints == baseline.constraints
    assert observed.planner_constraints == baseline.planner_constraints
    assert observed.reason == baseline.reason
