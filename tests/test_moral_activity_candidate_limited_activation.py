from __future__ import annotations

import json

import pytest

from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    BehaviorPlanningContext,
    SituationAnalysis,
)
from app.domain.morals import (
    MoralActivityCandidateApplicationCondition,
    MoralActivityCandidateApplicationConditionStatus,
    MoralActivityCandidatePreferenceShadow,
)
from app.runtime.behavior_planner import BehaviorPlanner
from app.runtime.moral_activity_candidate_limited_activation import (
    MoralActivityCandidateLimitedActivationApplier,
    MoralActivityCandidateLimitedActivationPolicy,
)
from app.runtime.situation_evaluator import SituationEvaluator


def _definition(activity_type: str) -> ActivityDefinition:
    return ActivityDefinition(
        activity_type=activity_type,
        display_name=activity_type,
        required_capability=None,
        provider_plugin_id="runtime",
        supported_operations=(ActivityOperation.START,),
        constraints_schema={"type": "object", "additionalProperties": False},
    )


def _context(*, event_type: str = "user_text") -> BehaviorPlanningContext:
    return BehaviorPlanningContext(
        user_text="候補の中から始めて",
        source_event_id="event-limited-activation-1",
        event_type=event_type,
        available_capabilities=frozenset(),
        activity_definitions=(
            _definition("first_activity"),
            _definition("preferred_activity"),
        ),
    )


def _analysis(
    *,
    activity_type: str = "first_activity",
    operation: ActivityOperation = ActivityOperation.START,
    evaluator_type: str = "llm",
) -> SituationAnalysis:
    return SituationAnalysis(
        activity_candidate=activity_type,
        operation=operation,
        goal="同等な候補からActivityを開始する",
        confidence=0.99,
        evaluator_type=evaluator_type,
    )


def _ready_shadow() -> MoralActivityCandidatePreferenceShadow:
    candidate_group = ("first_activity", "preferred_activity")
    return MoralActivityCandidatePreferenceShadow(
        static_eligible=True,
        preferred_activity_type="preferred_activity",
        candidate_group=candidate_group,
        current_order=candidate_group,
        hypothetical_order=("preferred_activity", "first_activity"),
        application_condition=MoralActivityCandidateApplicationCondition(
            candidate_group=candidate_group,
            preferred_activity_type="preferred_activity",
            status=MoralActivityCandidateApplicationConditionStatus.READY,
            static_eligible=True,
        ),
    )


def _enabled_applier(
    *allowlist: str,
) -> MoralActivityCandidateLimitedActivationApplier:
    return MoralActivityCandidateLimitedActivationApplier(
        MoralActivityCandidateLimitedActivationPolicy(
            enabled=True,
            allowlisted_activity_types=frozenset(allowlist),
        )
    )


def test_policy_defaults_to_disabled_and_empty_allowlist() -> None:
    policy = MoralActivityCandidateLimitedActivationPolicy.from_environment({})

    assert policy.enabled is False
    assert policy.allowlisted_activity_types == frozenset()


def test_policy_reads_explicit_environment_flag_and_allowlist() -> None:
    policy = MoralActivityCandidateLimitedActivationPolicy.from_environment(
        {
            MoralActivityCandidateLimitedActivationPolicy.ENV_ENABLED: "ON",
            MoralActivityCandidateLimitedActivationPolicy.ENV_ALLOWLIST: (
                " first_activity,preferred_activity, first_activity "
            ),
        }
    )

    assert policy.enabled is True
    assert policy.allowlisted_activity_types == frozenset(
        {"first_activity", "preferred_activity"}
    )


def test_policy_rejects_ambiguous_feature_flag() -> None:
    with pytest.raises(ValueError):
        MoralActivityCandidateLimitedActivationPolicy.from_environment(
            {
                MoralActivityCandidateLimitedActivationPolicy.ENV_ENABLED: "enable",
            }
        )


def test_disabled_policy_keeps_original_candidate() -> None:
    result, decision = MoralActivityCandidateLimitedActivationApplier(
        MoralActivityCandidateLimitedActivationPolicy(enabled=False)
    ).apply(_context(), _analysis(), _ready_shadow())

    assert result.activity_candidate == "first_activity"
    assert decision.applied is False
    assert decision.reason == "limited_activation_feature_disabled"


def test_ready_allowlisted_start_candidate_is_replaced() -> None:
    result, decision = _enabled_applier(
        "first_activity",
        "preferred_activity",
    ).apply(_context(), _analysis(), _ready_shadow())

    assert result.activity_candidate == "preferred_activity"
    assert decision.applied is True
    assert decision.original_activity_type == "first_activity"
    assert decision.selected_activity_type == "preferred_activity"
    assert decision.reason == "moral_candidate_limited_activation_applied"


def test_partial_allowlist_does_not_apply() -> None:
    result, decision = _enabled_applier("preferred_activity").apply(
        _context(),
        _analysis(),
        _ready_shadow(),
    )

    assert result.activity_candidate == "first_activity"
    assert decision.applied is False
    assert decision.reason == "limited_activation_candidate_group_not_allowlisted"


@pytest.mark.parametrize(
    ("analysis", "context", "expected_reason"),
    [
        (
            _analysis(operation=ActivityOperation.CONTINUE),
            _context(),
            "limited_activation_operation_not_start",
        ),
        (
            _analysis(evaluator_type="matcher"),
            _context(),
            "limited_activation_evaluator_not_eligible",
        ),
        (
            _analysis(),
            _context(event_type="curiosity_peak"),
            "limited_activation_event_type_not_eligible",
        ),
    ],
)
def test_limited_activation_keeps_noneligible_paths_unchanged(
    analysis: SituationAnalysis,
    context: BehaviorPlanningContext,
    expected_reason: str,
) -> None:
    result, decision = _enabled_applier(
        "first_activity",
        "preferred_activity",
    ).apply(context, analysis, _ready_shadow())

    assert result.activity_candidate == analysis.activity_candidate
    assert decision.applied is False
    assert decision.reason == expected_reason


class _SituationModel:
    async def evaluate(self, activity: object) -> str:
        del activity
        return json.dumps(
            {
                "activity_type": "first_activity",
                "operation": "start",
                "goal": "同等な候補からActivityを開始する",
                "constraints": {},
                "speech_act": "request",
                "negated": False,
                "hypothetical": False,
                "past_reference": False,
                "knowledge_question": False,
                "confidence": 0.99,
                "reason": "semantic_candidate_selected",
                "semantic_equivalence": {
                    "candidate_group": [
                        "first_activity",
                        "preferred_activity",
                    ],
                    "intent": "confirmed",
                    "operation": "confirmed",
                    "goal": "confirmed",
                    "reasons": ["same user intent"],
                },
            },
            ensure_ascii=False,
        )


class _PromptBuilder:
    def build(self, context: BehaviorPlanningContext) -> str:
        del context
        return "situation prompt"


class _ReadyShadowObserver:
    def observe(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> MoralActivityCandidatePreferenceShadow:
        del context, analysis
        return _ready_shadow()


@pytest.mark.asyncio
async def test_behavior_planner_uses_limited_activation_candidate() -> None:
    evaluator = SituationEvaluator(
        _SituationModel(),
        prompt_builder=_PromptBuilder(),
        semantic_equivalence_shadow_observer=_ReadyShadowObserver(),
        limited_activation_applier=_enabled_applier(
            "first_activity",
            "preferred_activity",
        ),
    )
    planner = BehaviorPlanner(situation_evaluator=evaluator)

    plan = await planner.plan(_context())

    assert plan.activity_type == "preferred_activity"
    assert plan.operation is ActivityOperation.START
    assert plan.planner_type == "llm"
