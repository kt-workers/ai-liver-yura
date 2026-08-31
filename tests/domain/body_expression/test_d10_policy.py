from datetime import datetime, timezone

import pytest

from app.domain.appraisal import FacetRef, InternalStateFacet, InternalStateSnapshot, StateFacetKind
from app.domain.attention import AttentionFocusView
from app.domain.body_expression import (
    BodyExpressionAxis,
    BodyExpressionAxisValue,
    BodyExpressionComponent,
    BodyExpressionContext,
    BodyExpressionDynamicGainOverride,
    BodyExpressionFailureCode,
    BodyExpressionInfluenceRule,
    BodyExpressionProjectionError,
    BodyExpressionProjectionPolicy,
    BodyExpressionTargetScope,
    BodyExpressionTransform,
    CharacterStyleInfluenceRule,
    CharacterStyleRuleDisposition,
    NormalizedExpressionValue,
    project,
)
from app.domain.character.contracts import (
    CharacterBodyStyleProfile,
    RuntimeAvailability,
    RuntimeCharacterFacet,
)

NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


def weight(axis: BodyExpressionAxis, value: float) -> BodyExpressionAxisValue:
    return BodyExpressionAxisValue(axis, NormalizedExpressionValue(value))


def gain(axis: BodyExpressionAxis, value: float) -> BodyExpressionDynamicGainOverride:
    return BodyExpressionDynamicGainOverride(axis, value)


def state_rule(axis: BodyExpressionAxis, value: float = 0.5) -> BodyExpressionInfluenceRule:
    return BodyExpressionInfluenceRule(
        "state.energy",
        StateFacetKind.ENERGY,
        None,
        BodyExpressionTargetScope.GLOBAL,
        BodyExpressionComponent.CURRENT,
        BodyExpressionTransform.SIGNED,
        (weight(axis, value),),
    )


def snapshot(current: float = 1.0) -> InternalStateSnapshot:
    facet = InternalStateFacet(
        FacetRef(StateFacetKind.ENERGY, "energy", None),
        current,
        0.0,
        current,
        1.0,
        ("event:1",),
        NOW,
    )
    return InternalStateSnapshot(1, 1, (facet,), NOW)


def attention() -> AttentionFocusView:
    return AttentionFocusView(1, 1, "attention", 1, None, None, (), None, None)


def style(*facets: RuntimeCharacterFacet) -> CharacterBodyStyleProfile:
    return CharacterBodyStyleProfile("yura", 1, 1, facets)


def confirmed(facet_id: str, value: str) -> RuntimeCharacterFacet:
    return RuntimeCharacterFacet(facet_id, RuntimeAvailability.CONFIRMED, value)


def axis_value(context: BodyExpressionContext, axis: BodyExpressionAxis) -> float:
    return next(item.value.value for item in context.axes if item.axis is axis)


def project_with(
    policy: BodyExpressionProjectionPolicy,
    character_style: CharacterBodyStyleProfile,
    *,
    current: float = 1.0,
) -> BodyExpressionContext:
    return project(
        snapshot(current),
        attention(),
        character_style,
        policy,
        revision=1,
        capture_source_context_revision=1,
        generated_at=NOW,
    )


def test_apply_keeps_static_baseline_and_gain_modulates_only_dynamic_state() -> None:
    axis = BodyExpressionAxis.MOVEMENT_AMPLITUDE
    rule = CharacterStyleInfluenceRule(
        "style.apply",
        "motion_softness",
        "soft",
        (weight(axis, 0.3),),
        (gain(axis, 1.2),),
        CharacterStyleRuleDisposition.APPLY,
    )
    policy = BodyExpressionProjectionPolicy("policy", 1, (state_rule(axis, 0.5),), (rule,))

    result = project_with(policy, style(confirmed("motion_softness", "soft")))

    assert axis_value(result, axis) == pytest.approx(0.9)


def test_dynamic_only_rule_creates_no_baseline_and_modulates_dynamic_state() -> None:
    axis = BodyExpressionAxis.GAZE_FREEDOM
    rule = CharacterStyleInfluenceRule(
        "style.dynamic",
        "gaze_tendency",
        "reactive",
        (),
        (gain(axis, 1.1),),
        CharacterStyleRuleDisposition.NO_BASELINE_ONLY_DYNAMIC,
    )
    policy = BodyExpressionProjectionPolicy("policy", 1, (state_rule(axis, 0.5),), (rule,))

    zero = project_with(policy, style(confirmed("gaze_tendency", "reactive")), current=0.0)
    active = project_with(policy, style(confirmed("gaze_tendency", "reactive")))

    assert axis_value(zero, axis) == 0.0
    assert axis_value(active, axis) == pytest.approx(0.55)


def test_explicit_ignore_counts_as_exact_mapping_without_creating_contribution() -> None:
    rule = CharacterStyleInfluenceRule(
        "style.ignore",
        "spatial_extent_tendency",
        "not-used",
        (),
        (),
        CharacterStyleRuleDisposition.IGNORE_EXPLICITLY,
    )
    policy = BodyExpressionProjectionPolicy("policy", 1, (), (rule,))

    result = project_with(
        policy,
        style(confirmed("spatial_extent_tendency", "not-used")),
        current=0.0,
    )

    assert result.applied_character_style_rule_ids == ("style.ignore",)
    assert all(item.value.value == 0.0 for item in result.axes)


def test_character_binding_is_exactly_one_per_facet_and_confirmed_value() -> None:
    first = CharacterStyleInfluenceRule(
        "style.1",
        "motion_softness",
        "soft",
        (weight(BodyExpressionAxis.MOTION_SOFTNESS, 0.2),),
    )
    second = CharacterStyleInfluenceRule(
        "style.2",
        "motion_softness",
        "soft",
        (weight(BodyExpressionAxis.MOTION_CONTINUITY, 0.2),),
    )

    with pytest.raises(ValueError, match="exactly one"):
        BodyExpressionProjectionPolicy("policy", 1, (), (first, second))


def test_disposition_contract_rejects_hidden_baseline_or_missing_gain() -> None:
    axis = BodyExpressionAxis.MOVEMENT_AMPLITUDE
    with pytest.raises(ValueError, match="gainだけ"):
        CharacterStyleInfluenceRule(
            "bad.dynamic",
            "amplitude_tendency",
            "dynamic",
            (weight(axis, 0.2),),
            (gain(axis, 1.1),),
            CharacterStyleRuleDisposition.NO_BASELINE_ONLY_DYNAMIC,
        )
    with pytest.raises(ValueError, match="寄与を持てません"):
        CharacterStyleInfluenceRule(
            "bad.ignore",
            "spatial_extent_tendency",
            "ignore",
            (),
            (gain(axis, 1.0),),
            CharacterStyleRuleDisposition.IGNORE_EXPLICITLY,
        )


def test_gain_product_over_closed_domain_fails_as_invalid_policy_at_projection() -> None:
    axis = BodyExpressionAxis.MOVEMENT_AMPLITUDE
    first = CharacterStyleInfluenceRule(
        "style.a",
        "amplitude_tendency",
        "a",
        (),
        (gain(axis, 1.5),),
        CharacterStyleRuleDisposition.NO_BASELINE_ONLY_DYNAMIC,
    )
    second = CharacterStyleInfluenceRule(
        "style.b",
        "gaze_tendency",
        "b",
        (),
        (gain(axis, 1.5),),
        CharacterStyleRuleDisposition.NO_BASELINE_ONLY_DYNAMIC,
    )
    policy = BodyExpressionProjectionPolicy("policy", 1, (state_rule(axis),), (first, second))

    with pytest.raises(BodyExpressionProjectionError) as error:
        project_with(
            policy,
            style(
                confirmed("amplitude_tendency", "a"),
                confirmed("gaze_tendency", "b"),
            ),
        )
    assert error.value.code is BodyExpressionFailureCode.INVALID_POLICY


def test_gain_value_must_be_finite_closed_zero_to_two() -> None:
    for value in (-0.01, 2.01, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            gain(BodyExpressionAxis.MOVEMENT_ENERGY, value)
