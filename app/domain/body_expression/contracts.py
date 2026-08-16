from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.appraisal import StateFacetKind
from app.domain.attention import AttentionFocusView
from app.domain.contracts.common import require_aware, require_identifier, require_revision


class BodyExpressionAxis(str, Enum):
    POSTURE_EXPRESSIVENESS = "posture_expressiveness"
    MOVEMENT_ENERGY = "movement_energy"
    MOVEMENT_AMPLITUDE = "movement_amplitude"
    MOTION_SOFTNESS = "motion_softness"
    SPATIAL_EXTENT = "spatial_extent"
    MOTION_CONTINUITY = "motion_continuity"
    MOVEMENT_TEMPO = "movement_tempo"
    GAZE_FREEDOM = "gaze_freedom"
    HEAD_EXPRESSIVENESS = "head_expressiveness"
    TORSO_EXPRESSIVENESS = "torso_expressiveness"
    SYMMETRY = "symmetry"
    COORDINATION = "coordination"
    BREATHING_AMPLITUDE = "breathing_amplitude"
    BREATHING_TEMPO = "breathing_tempo"
    IDLE_VARIATION = "idle_variation"
    GESTURE_DENSITY = "gesture_density"


_BODY_STYLE_FACET_IDS = frozenset(
    {
        "amplitude_tendency",
        "continuity_tendency",
        "gaze_tendency",
        "head_expression_tendency",
        "motion_softness",
        "posture_expression_tendency",
        "spatial_extent_tendency",
        "symmetry_tendency",
    }
)


def _normalized(value: float, field_name: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or not -1.0 <= value <= 1.0:
        raise ValueError(f"{field_name} は有限の [-1, 1] でなければなりません")
    return float(value)


@dataclass(frozen=True, slots=True)
class NormalizedExpressionValue:
    value: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _normalized(self.value, "value"))


@dataclass(frozen=True, slots=True)
class BodyExpressionAxisValue:
    axis: BodyExpressionAxis
    value: NormalizedExpressionValue

    def __post_init__(self) -> None:
        if not isinstance(self.axis, BodyExpressionAxis):
            raise ValueError("axis は BodyExpressionAxis でなければなりません")
        if not isinstance(self.value, NormalizedExpressionValue):
            raise ValueError("value は NormalizedExpressionValue でなければなりません")


@dataclass(frozen=True, slots=True)
class BodyFocusExpressionConstraint:
    foreground_focus_ref: str | None
    active_focus_intent_ref: str | None
    secondary_monitor_refs: tuple[str, ...]
    current_turn_owner: str | None
    response_obligation: str | None

    def __post_init__(self) -> None:
        for field_name in (
            "foreground_focus_ref",
            "active_focus_intent_ref",
            "current_turn_owner",
            "response_obligation",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name)
        refs = tuple(self.secondary_monitor_refs)
        if any(not isinstance(reference, str) or not reference.strip() for reference in refs):
            raise ValueError("secondary_monitor_refs は空でない文字列だけを含みます")
        if len(refs) != len(set(refs)):
            raise ValueError("secondary_monitor_refs は重複できません")
        object.__setattr__(self, "secondary_monitor_refs", refs)

    @classmethod
    def from_view(cls, view: AttentionFocusView) -> BodyFocusExpressionConstraint:
        if not isinstance(view, AttentionFocusView):
            raise ValueError("view は AttentionFocusView でなければなりません")
        return cls(
            foreground_focus_ref=view.foreground_focus_ref,
            active_focus_intent_ref=view.active_focus_intent_ref,
            secondary_monitor_refs=view.secondary_monitor_refs,
            current_turn_owner=view.current_turn_owner,
            response_obligation=view.response_obligation,
        )


class BodyExpressionComponent(str, Enum):
    CURRENT = "current"
    DELTA = "delta"


class BodyExpressionTransform(str, Enum):
    SIGNED = "signed"
    MAGNITUDE = "magnitude"
    POSITIVE_ONLY = "positive_only"
    NEGATIVE_MAGNITUDE = "negative_magnitude"


class BodyExpressionTargetScope(str, Enum):
    GLOBAL = "global"
    ANY_TARGET = "any_target"
    FOREGROUND = "foreground"
    TURN_OWNER = "turn_owner"


def _axis_weights(
    values: tuple[BodyExpressionAxisValue, ...],
) -> tuple[BodyExpressionAxisValue, ...]:
    result = tuple(values)
    if not result or any(not isinstance(item, BodyExpressionAxisValue) for item in result):
        raise ValueError("axis_weights は空でない BodyExpressionAxisValue の列でなければなりません")
    if len({item.axis for item in result}) != len(result):
        raise ValueError("axis_weights の axis は一意でなければなりません")
    return result


@dataclass(frozen=True, slots=True)
class BodyExpressionInfluenceRule:
    rule_id: str
    facet_kind: StateFacetKind
    state_key: str | None
    target_scope: BodyExpressionTargetScope
    component: BodyExpressionComponent
    transform: BodyExpressionTransform
    axis_weights: tuple[BodyExpressionAxisValue, ...]

    def __post_init__(self) -> None:
        require_identifier(self.rule_id, "rule_id")
        if not isinstance(self.facet_kind, StateFacetKind):
            raise ValueError("facet_kind は StateFacetKind でなければなりません")
        if self.state_key is not None:
            require_identifier(self.state_key, "state_key")
        if not isinstance(self.target_scope, BodyExpressionTargetScope):
            raise ValueError("target_scope が不正です")
        if not isinstance(self.component, BodyExpressionComponent):
            raise ValueError("component が不正です")
        if not isinstance(self.transform, BodyExpressionTransform):
            raise ValueError("transform が不正です")
        object.__setattr__(self, "axis_weights", _axis_weights(self.axis_weights))


@dataclass(frozen=True, slots=True)
class CharacterStyleInfluenceRule:
    rule_id: str
    facet_id: str
    confirmed_value: str
    axis_weights: tuple[BodyExpressionAxisValue, ...]

    def __post_init__(self) -> None:
        require_identifier(self.rule_id, "rule_id")
        require_identifier(self.facet_id, "facet_id")
        if self.facet_id not in _BODY_STYLE_FACET_IDS:
            raise ValueError("facet_id は既知の Character Body Style facet でなければなりません")
        require_identifier(self.confirmed_value, "confirmed_value")
        object.__setattr__(self, "axis_weights", _axis_weights(self.axis_weights))


@dataclass(frozen=True, slots=True)
class BodyExpressionProjectionPolicy:
    policy_id: str
    policy_revision: int
    state_rules: tuple[BodyExpressionInfluenceRule, ...] = ()
    character_style_rules: tuple[CharacterStyleInfluenceRule, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        state_rules = tuple(self.state_rules)
        character_style_rules = tuple(self.character_style_rules)
        if any(not isinstance(rule, BodyExpressionInfluenceRule) for rule in state_rules):
            raise ValueError("state_rules が不正です")
        if any(not isinstance(rule, CharacterStyleInfluenceRule) for rule in character_style_rules):
            raise ValueError("character_style_rules が不正です")
        identifiers = [
            *(rule.rule_id for rule in state_rules),
            *(rule.rule_id for rule in character_style_rules),
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("policy 内の rule_id は一意でなければなりません")
        object.__setattr__(self, "state_rules", state_rules)
        object.__setattr__(self, "character_style_rules", character_style_rules)


@dataclass(frozen=True, slots=True)
class BodyExpressionContext:
    revision: int
    capture_source_context_revision: int
    internal_state_revision: int
    internal_state_source_context_revision: int
    attention_revision: int
    attention_source_context_revision: int
    character_id: str
    character_schema_version: int
    character_definition_revision: int
    projection_policy_id: str
    projection_policy_revision: int
    axes: tuple[BodyExpressionAxisValue, ...]
    focus_constraint: BodyFocusExpressionConstraint
    applied_state_rule_ids: tuple[str, ...]
    applied_character_style_rule_ids: tuple[str, ...]
    source_facet_refs: tuple[str, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "revision",
            "capture_source_context_revision",
            "internal_state_revision",
            "internal_state_source_context_revision",
            "attention_revision",
            "attention_source_context_revision",
            "character_definition_revision",
            "projection_policy_revision",
        ):
            require_revision(getattr(self, field_name), field_name)
        require_identifier(self.character_id, "character_id")
        if type(self.character_schema_version) is not int or self.character_schema_version != 1:
            raise ValueError("未対応の character_schema_version です")
        require_identifier(self.projection_policy_id, "projection_policy_id")
        axes = tuple(self.axes)
        if any(not isinstance(axis, BodyExpressionAxisValue) for axis in axes):
            raise ValueError("axes が不正です")
        if len(axes) != len(BodyExpressionAxis) or {axis.axis for axis in axes} != set(
            BodyExpressionAxis
        ):
            raise ValueError("axes は全 BodyExpressionAxis を一度ずつ持たなければなりません")
        if not isinstance(self.focus_constraint, BodyFocusExpressionConstraint):
            raise ValueError("focus_constraint が不正です")
        for field_name in (
            "applied_state_rule_ids",
            "applied_character_style_rule_ids",
            "source_facet_refs",
        ):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{field_name} は空でない文字列だけを含みます")
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} は重複できません")
            object.__setattr__(self, field_name, tuple(sorted(values)))
        require_aware(self.generated_at, "generated_at")
        object.__setattr__(self, "axes", tuple(sorted(axes, key=lambda item: item.axis.value)))


class BodyExpressionFailureCode(str, Enum):
    UNMAPPED_CHARACTER_STYLE = "unmapped_character_style"
    STALE = "stale"
    INCOHERENT = "incoherent"
    DETERMINISM = "determinism"


class BodyExpressionProjectionError(ValueError):
    def __init__(self, code: BodyExpressionFailureCode) -> None:
        super().__init__(code.value)
        self.code = code
