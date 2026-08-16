from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from math import inf, nan

import pytest

from app.domain.appraisal import FacetRef, InternalStateFacet, InternalStateSnapshot, StateFacetKind
from app.domain.attention import AttentionFocusView
from app.domain.body_expression import (
    BodyExpressionAxis,
    BodyExpressionAxisValue,
    BodyExpressionComponent,
    BodyExpressionContext,
    BodyExpressionCoordinator,
    BodyExpressionFailureCode,
    BodyExpressionInfluenceRule,
    BodyExpressionProjectionError,
    BodyExpressionProjectionPolicy,
    BodyExpressionStore,
    BodyExpressionTargetScope,
    BodyExpressionTransform,
    CharacterStyleInfluenceRule,
    NormalizedExpressionValue,
    project,
)
from app.domain.character.contracts import (
    CharacterBodyStyleProfile,
    RuntimeAvailability,
    RuntimeCharacterFacet,
)

NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)


def _weight(axis: BodyExpressionAxis, value: float) -> BodyExpressionAxisValue:
    return BodyExpressionAxisValue(axis, NormalizedExpressionValue(value))


def _style(
    value: str | None = "soft", *, availability: RuntimeAvailability = RuntimeAvailability.CONFIRMED
) -> CharacterBodyStyleProfile:
    return CharacterBodyStyleProfile(
        "generic", 1, 3, (RuntimeCharacterFacet("motion_softness", availability, value),)
    )


def _attention(*, foreground: str | None = None, owner: str | None = None) -> AttentionFocusView:
    return AttentionFocusView(4, 8, "attention_policy", 1, foreground, None, (), owner, None)


def _snapshot(*facets: InternalStateFacet) -> InternalStateSnapshot:
    return InternalStateSnapshot(5, 8, facets, NOW)


def _facet(
    kind: StateFacetKind = StateFacetKind.EMOTION,
    key: str = "joy",
    *,
    target: str | None = None,
    current: float = 0.5,
    delta: float = 0.2,
    confidence: float = 0.8,
) -> InternalStateFacet:
    return InternalStateFacet(
        FacetRef(kind, key, target),
        current,
        current - delta,
        delta,
        confidence,
        ("event:1",),
        NOW,
    )


def _policy(
    *,
    state_rules: tuple[BodyExpressionInfluenceRule, ...] = (),
    character_rules: tuple[CharacterStyleInfluenceRule, ...] = (),
) -> BodyExpressionProjectionPolicy:
    return BodyExpressionProjectionPolicy("body_expression", 2, state_rules, character_rules)


def _project(
    policy: BodyExpressionProjectionPolicy,
    snapshot: InternalStateSnapshot | None = None,
    style: CharacterBodyStyleProfile | None = None,
    attention: AttentionFocusView | None = None,
) -> BodyExpressionContext:
    return project(
        snapshot or _snapshot(),
        attention or _attention(),
        style or _style(),
        policy,
        revision=1,
        capture_source_context_revision=8,
        generated_at=NOW,
    )


def _axis(context: BodyExpressionContext, axis: BodyExpressionAxis) -> float:
    return next(item.value.value for item in context.axes if item.axis is axis)


@pytest.mark.parametrize("value", (-1.0, 0.0, 1.0))
def test_normalized_value_accepts_unit_domain(value: float) -> None:
    assert NormalizedExpressionValue(value).value == value


@pytest.mark.parametrize("value", (nan, inf, -inf, 1.01, -1.01))
def test_normalized_value_rejects_non_finite_or_out_of_range(value: float) -> None:
    with pytest.raises(ValueError):
        NormalizedExpressionValue(value)


def test_character_style_uses_exact_value_only_and_unmapped_is_typed_failure() -> None:
    policy = _policy(
        character_rules=(
            CharacterStyleInfluenceRule(
                "soft",
                "motion_softness",
                "soft",
                (_weight(BodyExpressionAxis.MOTION_SOFTNESS, 0.6),),
            ),
        )
    )
    assert _axis(_project(policy), BodyExpressionAxis.MOTION_SOFTNESS) == pytest.approx(0.6)
    for value in ("Soft", "very soft", "softly"):
        with pytest.raises(BodyExpressionProjectionError) as error:
            _project(policy, style=_style(value))
        assert error.value.code is BodyExpressionFailureCode.UNMAPPED_CHARACTER_STYLE


def test_unresolved_style_does_not_invent_character_value() -> None:
    result = _project(_policy(), style=_style(None, availability=RuntimeAvailability.UNRESOLVED))
    assert _axis(result, BodyExpressionAxis.MOTION_SOFTNESS) == 0.0


def test_state_current_delta_confidence_target_and_clamp_are_explicit() -> None:
    current = BodyExpressionInfluenceRule(
        "current",
        StateFacetKind.EMOTION,
        "joy",
        BodyExpressionTargetScope.GLOBAL,
        BodyExpressionComponent.CURRENT,
        BodyExpressionTransform.SIGNED,
        (_weight(BodyExpressionAxis.MOVEMENT_ENERGY, 1.0),),
    )
    delta = BodyExpressionInfluenceRule(
        "delta",
        StateFacetKind.RELATIONSHIP,
        "trust",
        BodyExpressionTargetScope.FOREGROUND,
        BodyExpressionComponent.DELTA,
        BodyExpressionTransform.MAGNITUDE,
        (_weight(BodyExpressionAxis.MOVEMENT_ENERGY, 1.0),),
    )
    result = _project(
        _policy(state_rules=(current, delta)),
        _snapshot(
            _facet(current=1.0, confidence=1.0),
            _facet(
                StateFacetKind.RELATIONSHIP,
                "trust",
                target="user:1",
                current=-0.5,
                delta=-0.8,
                confidence=1.0,
            ),
        ),
        _style(None, availability=RuntimeAvailability.NOT_CONFIGURED),
        _attention(foreground="user:1"),
    )
    assert _axis(result, BodyExpressionAxis.MOVEMENT_ENERGY) == 1.0
    assert result.source_facet_refs == ("emotion.joy", "relationship.trust.user:1")


def test_focus_is_categorical_and_does_not_create_numeric_gaze_bias() -> None:
    result = _project(
        _policy(),
        style=_style(None, availability=RuntimeAvailability.NOT_CONFIGURED),
        attention=_attention(foreground="user:1", owner="turn:1"),
    )
    assert result.focus_constraint.foreground_focus_ref == "user:1"
    assert result.focus_constraint.current_turn_owner == "turn:1"
    assert _axis(result, BodyExpressionAxis.GAZE_FREEDOM) == 0.0


def test_policy_rejects_duplicate_rules_invalid_weights_and_unknown_style_facet() -> None:
    with pytest.raises(ValueError):
        CharacterStyleInfluenceRule(
            "bad", "unknown", "value", (_weight(BodyExpressionAxis.MOTION_SOFTNESS, 0.1),)
        )
    with pytest.raises(ValueError):
        CharacterStyleInfluenceRule(
            "duplicate_axis",
            "motion_softness",
            "soft",
            (
                _weight(BodyExpressionAxis.MOTION_SOFTNESS, 0.1),
                _weight(BodyExpressionAxis.MOTION_SOFTNESS, 0.2),
            ),
        )
    state_rule = BodyExpressionInfluenceRule(
        "same",
        StateFacetKind.EMOTION,
        None,
        BodyExpressionTargetScope.ANY_TARGET,
        BodyExpressionComponent.CURRENT,
        BodyExpressionTransform.SIGNED,
        (_weight(BodyExpressionAxis.MOVEMENT_ENERGY, 0.2),),
    )
    with pytest.raises(ValueError):
        _policy(
            state_rules=(state_rule,),
            character_rules=(
                CharacterStyleInfluenceRule(
                    "same",
                    "motion_softness",
                    "soft",
                    (_weight(BodyExpressionAxis.MOTION_SOFTNESS, 0.2),),
                ),
            ),
        )


def test_store_rejects_stale_commit_and_preserves_previous_context() -> None:
    candidate = _project(
        _policy(), style=_style(None, availability=RuntimeAvailability.NOT_CONFIGURED)
    )
    store = BodyExpressionStore()
    accepted = store.commit(0, candidate)
    with pytest.raises(BodyExpressionProjectionError) as error:
        store.commit(0, replace(candidate, revision=1))
    assert error.value.code is BodyExpressionFailureCode.STALE
    assert store.current is accepted


def test_store_detects_non_deterministic_recalculation_and_idempotent_replay() -> None:
    candidate = _project(
        _policy(), style=_style(None, availability=RuntimeAvailability.NOT_CONFIGURED)
    )
    store = BodyExpressionStore()
    accepted = store.commit(0, candidate)
    replay = replace(candidate, revision=2)
    assert store.commit(1, replay) is accepted
    different_axes = tuple(
        replace(item, value=NormalizedExpressionValue(0.2))
        if item.axis is BodyExpressionAxis.GAZE_FREEDOM
        else item
        for item in candidate.axes
    )
    with pytest.raises(BodyExpressionProjectionError) as error:
        store.commit(1, replace(candidate, revision=2, axes=different_axes))
    assert error.value.code is BodyExpressionFailureCode.DETERMINISM


class _StatePort:
    def __init__(self, value: InternalStateSnapshot) -> None:
        self._value = value

    def current_snapshot(self) -> InternalStateSnapshot:
        return self._value


class _AttentionPort:
    def __init__(self, value: AttentionFocusView) -> None:
        self._value = value

    def current_view(self) -> AttentionFocusView:
        return self._value


class _CharacterPort:
    def __init__(self, value: CharacterBodyStyleProfile) -> None:
        self._value = value

    def current_profile(self) -> CharacterBodyStyleProfile:
        return self._value


class _PolicyPort:
    def __init__(self, value: BodyExpressionProjectionPolicy) -> None:
        self._value = value

    def current_policy(self) -> BodyExpressionProjectionPolicy:
        return self._value


class _LiveContextPort:
    def __init__(self, revisions: list[int]) -> None:
        self._revisions = revisions

    def current_source_context_revision(self) -> int:
        return self._revisions.pop(0)


def test_coordinator_commits_only_a_stable_multi_owner_cut() -> None:
    coordinator = BodyExpressionCoordinator(
        _StatePort(_snapshot()),
        _AttentionPort(_attention()),
        _CharacterPort(_style(None, availability=RuntimeAvailability.NOT_CONFIGURED)),
        _PolicyPort(_policy()),
        _LiveContextPort([8, 8]),
        BodyExpressionStore(),
    )
    result = coordinator.refresh(NOW)
    assert result.capture_source_context_revision == 8
    assert result.revision == 1


def test_coordinator_rejects_changed_global_generation_without_commit() -> None:
    store = BodyExpressionStore()
    coordinator = BodyExpressionCoordinator(
        _StatePort(_snapshot()),
        _AttentionPort(_attention()),
        _CharacterPort(_style(None, availability=RuntimeAvailability.NOT_CONFIGURED)),
        _PolicyPort(_policy()),
        _LiveContextPort([8, 9]),
        store,
        max_stable_read_attempts=1,
    )
    with pytest.raises(BodyExpressionProjectionError) as error:
        coordinator.refresh(NOW)
    assert error.value.code is BodyExpressionFailureCode.INCOHERENT
    assert store.current is None
