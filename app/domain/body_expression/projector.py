from __future__ import annotations

from datetime import datetime
from math import fsum

from app.domain.appraisal import InternalStateFacet, InternalStateSnapshot
from app.domain.attention import AttentionFocusView
from app.domain.character.contracts import CharacterBodyStyleProfile, RuntimeAvailability

from .contracts import (
    BodyExpressionAxis,
    BodyExpressionAxisValue,
    BodyExpressionComponent,
    BodyExpressionContext,
    BodyExpressionFailureCode,
    BodyExpressionInfluenceRule,
    BodyExpressionProjectionError,
    BodyExpressionProjectionPolicy,
    BodyExpressionTargetScope,
    BodyExpressionTransform,
    BodyFocusExpressionConstraint,
    NormalizedExpressionValue,
)


def _transform(value: float, transform: BodyExpressionTransform) -> float:
    if transform is BodyExpressionTransform.SIGNED:
        return value
    if transform is BodyExpressionTransform.MAGNITUDE:
        return abs(value)
    if transform is BodyExpressionTransform.POSITIVE_ONLY:
        return max(value, 0.0)
    if transform is BodyExpressionTransform.NEGATIVE_MAGNITUDE:
        return max(-value, 0.0)
    raise AssertionError("未対応の transform です")


def _matches_scope(
    rule: BodyExpressionInfluenceRule,
    facet: InternalStateFacet,
    focus: BodyFocusExpressionConstraint,
) -> bool:
    target_ref = facet.ref.target_ref
    if rule.target_scope is BodyExpressionTargetScope.GLOBAL:
        return target_ref is None
    if rule.target_scope is BodyExpressionTargetScope.ANY_TARGET:
        return True
    if rule.target_scope is BodyExpressionTargetScope.FOREGROUND:
        return (
            target_ref is not None
            and focus.foreground_focus_ref is not None
            and target_ref == focus.foreground_focus_ref
        )
    if rule.target_scope is BodyExpressionTargetScope.TURN_OWNER:
        return (
            target_ref is not None
            and focus.current_turn_owner is not None
            and target_ref == focus.current_turn_owner
        )
    raise AssertionError("未対応の target_scope です")


def _matches_state_rule(
    rule: BodyExpressionInfluenceRule,
    facet: InternalStateFacet,
    focus: BodyFocusExpressionConstraint,
) -> bool:
    return (
        rule.facet_kind is facet.ref.kind
        and (rule.state_key is None or rule.state_key == facet.ref.state_key)
        and _matches_scope(rule, facet, focus)
    )


def _facet_reference(facet: InternalStateFacet) -> str:
    if facet.ref.target_ref is None:
        return f"{facet.ref.kind.value}.{facet.ref.state_key}"
    return f"{facet.ref.kind.value}.{facet.ref.state_key}.{facet.ref.target_ref}"


def project(
    snapshot: InternalStateSnapshot,
    attention: AttentionFocusView,
    style: CharacterBodyStyleProfile,
    policy: BodyExpressionProjectionPolicy,
    *,
    revision: int,
    capture_source_context_revision: int,
    generated_at: datetime,
) -> BodyExpressionContext:
    """immutable source snapshots から BodyExpressionContext を決定論的に投影する。"""
    focus = BodyFocusExpressionConstraint.from_view(attention)
    contributions: dict[BodyExpressionAxis, list[float]] = {axis: [] for axis in BodyExpressionAxis}
    applied_state_rule_ids: list[str] = []
    applied_character_rule_ids: list[str] = []
    source_facet_refs: list[str] = []

    for style_facet in sorted(style.facets, key=lambda item: item.facet_id):
        if style_facet.availability is not RuntimeAvailability.CONFIRMED:
            continue
        style_matching_rules = sorted(
            (
                rule
                for rule in policy.character_style_rules
                if (
                    rule.facet_id == style_facet.facet_id
                    and rule.confirmed_value == style_facet.value
                )
            ),
            key=lambda rule: rule.rule_id,
        )
        if not style_matching_rules:
            raise BodyExpressionProjectionError(BodyExpressionFailureCode.UNMAPPED_CHARACTER_STYLE)
        for style_rule in style_matching_rules:
            applied_character_rule_ids.append(style_rule.rule_id)
            for weight in style_rule.axis_weights:
                contributions[weight.axis].append(weight.value.value)

    for state_facet in sorted(
        snapshot.facets,
        key=lambda item: (item.ref.kind.value, item.ref.state_key, item.ref.target_ref or ""),
    ):
        state_matching_rules = sorted(
            (rule for rule in policy.state_rules if _matches_state_rule(rule, state_facet, focus)),
            key=lambda rule: rule.rule_id,
        )
        for state_rule in state_matching_rules:
            component = (
                state_facet.current
                if state_rule.component is BodyExpressionComponent.CURRENT
                else state_facet.last_delta
            )
            signal = _transform(component, state_rule.transform) * state_facet.confidence
            applied_state_rule_ids.append(state_rule.rule_id)
            source_facet_refs.append(_facet_reference(state_facet))
            for weight in state_rule.axis_weights:
                contributions[weight.axis].append(signal * weight.value.value)

    axes = tuple(
        BodyExpressionAxisValue(
            axis=axis,
            value=NormalizedExpressionValue(max(-1.0, min(1.0, fsum(contributions[axis])))),
        )
        for axis in BodyExpressionAxis
    )
    return BodyExpressionContext(
        revision=revision,
        capture_source_context_revision=capture_source_context_revision,
        internal_state_revision=snapshot.revision,
        internal_state_source_context_revision=snapshot.source_context_revision,
        attention_revision=attention.revision,
        attention_source_context_revision=attention.source_context_revision,
        character_id=style.character_id,
        character_schema_version=style.schema_version,
        character_definition_revision=style.definition_revision,
        projection_policy_id=policy.policy_id,
        projection_policy_revision=policy.policy_revision,
        axes=axes,
        focus_constraint=focus,
        applied_state_rule_ids=tuple(sorted(set(applied_state_rule_ids))),
        applied_character_style_rule_ids=tuple(sorted(set(applied_character_rule_ids))),
        source_facet_refs=tuple(sorted(set(source_facet_refs))),
        generated_at=generated_at,
    )
