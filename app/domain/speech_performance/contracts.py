from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.appraisal import StateFacetKind
from app.domain.character.contracts import CharacterVoiceStyleProfile
from app.domain.character_language import CharacterUtterance
from app.domain.contracts.common import (
    RevisionVector,
    require_aware,
    require_identifier,
    require_revision,
    utc_instant,
)


def normalized(value: float, name: str, low: float = -1.0, high: float = 1.0) -> float:
    if type(value) not in (int, float) or not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} は有限の [{low}, {high}] でなければなりません")
    return float(value)


class PerformanceAxis(str, Enum):
    PACE = "pace"
    ENERGY = "energy"
    PITCH_CENTER = "pitch_center"
    PITCH_RANGE = "pitch_range"
    LOUDNESS = "loudness"
    SOFTNESS = "softness"
    BREATHINESS = "breathiness"
    TENSION = "tension"
    EXPRESSIVENESS = "expressiveness"


class ExpressionAxis(str, Enum):
    ACTIVATION = "activation"
    ENERGY = "energy"
    SOFTNESS = "softness"
    TENSION = "tension"
    WARMTH = "warmth"
    EXPRESSIVENESS = "expressiveness"
    PACING_BIAS = "pacing_bias"
    EMPHASIS_BIAS = "emphasis_bias"


class StateTargetScope(str, Enum):
    GLOBAL = "global"
    TURN_OWNER = "turn_owner"
    FOREGROUND_FOCUS = "foreground_focus"
    SPEECH_TARGET = "speech_target"


class ConstraintCombinationMode(str, Enum):
    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class SpeechPerformanceDegradationReason(str, Enum):
    UNMAPPED_CHARACTER_VOICE_STYLE = "unmapped_character_voice_style"
    INVALID_PERFORMANCE_PROJECTION_POLICY = "invalid_performance_projection_policy"
    EXPRESSION_CONTEXT_UNAVAILABLE = "expression_context_unavailable"
    CHARACTER_VOICE_STYLE_UNAVAILABLE = "character_voice_style_unavailable"
    SYSTEM_NEUTRAL_FALLBACK = "system_neutral_fallback"


class StateComponent(str, Enum):
    CURRENT = "current"
    DELTA = "delta"


class StateTransform(str, Enum):
    SIGNED = "signed"
    MAGNITUDE = "magnitude"
    POSITIVE_ONLY = "positive_only"
    NEGATIVE_MAGNITUDE = "negative_magnitude"


@dataclass(frozen=True, slots=True)
class PerformanceIntentVector:
    values: tuple[tuple[PerformanceAxis, float], ...]

    def __post_init__(self) -> None:
        values = tuple(self.values)
        if {axis for axis, _ in values} != set(PerformanceAxis) or len(values) != len(
            PerformanceAxis
        ):
            raise ValueError("values は全PerformanceAxisを一度ずつ持ちます")
        object.__setattr__(
            self,
            "values",
            tuple((axis, normalized(value, axis.value)) for axis, value in values),
        )

    @classmethod
    def neutral(cls) -> PerformanceIntentVector:
        return cls(tuple((axis, 0.0) for axis in PerformanceAxis))

    def get(self, axis: PerformanceAxis) -> float:
        return dict(self.values)[axis]


@dataclass(frozen=True, slots=True)
class PerformanceIntentDelta:
    values: tuple[tuple[PerformanceAxis, float], ...]

    def __post_init__(self) -> None:
        values = tuple(self.values)
        if len({axis for axis, _ in values}) != len(values):
            raise ValueError("delta axis は重複できません")
        object.__setattr__(
            self,
            "values",
            tuple((axis, normalized(value, axis.value)) for axis, value in values),
        )


@dataclass(frozen=True, slots=True)
class CharacterVoiceStyleInfluenceRule:
    rule_id: str
    character_id: str
    facet_id: str
    expected_confirmed_value: str
    baseline_delta: PerformanceIntentDelta
    dynamic_gains: tuple[tuple[ExpressionAxis, float], ...] = ()

    def __post_init__(self) -> None:
        for name in ("rule_id", "character_id", "facet_id", "expected_confirmed_value"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.baseline_delta, PerformanceIntentDelta):
            raise ValueError("baseline_delta が不正です")
        gains = tuple(self.dynamic_gains)
        if len({axis for axis, _ in gains}) != len(gains):
            raise ValueError("dynamic_gains は一意です")
        object.__setattr__(
            self,
            "dynamic_gains",
            tuple(
                (axis, normalized(value, axis.value, 0.0, 2.0))
                for axis, value in gains
                if isinstance(axis, ExpressionAxis)
            ),
        )
        if len(self.dynamic_gains) != len(gains):
            raise ValueError("dynamic_gains のaxisが不正です")


@dataclass(frozen=True, slots=True)
class SpeechStateInfluenceRule:
    rule_id: str
    facet_kind: StateFacetKind
    state_key: str | None
    target_scope: StateTargetScope
    component: StateComponent
    transform: StateTransform
    expression_delta: tuple[tuple[ExpressionAxis, float], ...]

    def __post_init__(self) -> None:
        require_identifier(self.rule_id, "rule_id")
        if not isinstance(self.facet_kind, StateFacetKind):
            raise ValueError("facet_kind が不正です")
        if self.state_key is not None:
            require_identifier(self.state_key, "state_key")
        if not isinstance(self.target_scope, StateTargetScope):
            raise ValueError("target_scope が不正です")
        if not isinstance(self.component, StateComponent) or not isinstance(
            self.transform, StateTransform
        ):
            raise ValueError("state rule の型が不正です")
        values = tuple(self.expression_delta)
        if not values or len({axis for axis, _ in values}) != len(values):
            raise ValueError("expression_delta が不正です")
        if any(not isinstance(axis, ExpressionAxis) for axis, _ in values):
            raise ValueError("expression_delta のaxisが不正です")
        object.__setattr__(
            self,
            "expression_delta",
            tuple((axis, normalized(value, axis.value)) for axis, value in values),
        )


@dataclass(frozen=True, slots=True)
class ExpressionPerformanceRule:
    expression_axis: ExpressionAxis
    performance_delta: PerformanceIntentDelta

    def __post_init__(self) -> None:
        if not isinstance(self.expression_axis, ExpressionAxis):
            raise ValueError("expression_axis が不正です")


@dataclass(frozen=True, slots=True)
class LinguisticPerformancePolicy:
    continue_boundary_min: float
    phrase_boundary_min: float
    sentence_boundary_min: float
    emphasized_min_strength: float
    deemphasized_max_strength: float
    hesitant_min_strength: float

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, normalized(getattr(self, name), name, 0.0, 1.0))
        if not self.continue_boundary_min <= self.phrase_boundary_min <= self.sentence_boundary_min:
            raise ValueError("boundary strength は単調増加です")
        if self.deemphasized_max_strength > self.emphasized_min_strength:
            raise ValueError("deemphasized はemphasizedを超えません")


@dataclass(frozen=True, slots=True)
class SpeechPerformanceProjectionPolicy:
    policy_id: str
    policy_revision: int
    character_style_rules: tuple[CharacterVoiceStyleInfluenceRule, ...]
    state_rules: tuple[SpeechStateInfluenceRule, ...]
    expression_rules: tuple[ExpressionPerformanceRule, ...]
    linguistic_rules: LinguisticPerformancePolicy
    constraint_rules: tuple[SpeechPerformanceConstraintRule, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        if not isinstance(self.linguistic_rules, LinguisticPerformancePolicy):
            raise ValueError("linguistic_rules が不正です")
        for name, expected in (
            ("character_style_rules", CharacterVoiceStyleInfluenceRule),
            ("state_rules", SpeechStateInfluenceRule),
            ("expression_rules", ExpressionPerformanceRule),
            ("constraint_rules", SpeechPerformanceConstraintRule),
        ):
            values = tuple(getattr(self, name))
            if any(not isinstance(item, expected) for item in values):
                raise ValueError(f"{name} が不正です")
            object.__setattr__(self, name, values)


@dataclass(frozen=True, slots=True)
class SpeechPerformanceConstraintRule:
    kind: str
    combination_mode: ConstraintCombinationMode
    affected_axes: tuple[PerformanceAxis, ...]

    def __post_init__(self) -> None:
        require_identifier(self.kind, "kind")
        if not isinstance(self.combination_mode, ConstraintCombinationMode):
            raise ValueError("combination_mode が不正です")
        if not self.affected_axes or any(
            not isinstance(axis, PerformanceAxis) for axis in self.affected_axes
        ):
            raise ValueError("affected_axes が不正です")


@dataclass(frozen=True, slots=True)
class PitchAnchor:
    position: float
    relative_pitch: float
    strength: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", normalized(self.position, "position", 0.0, 1.0))
        object.__setattr__(
            self,
            "relative_pitch",
            normalized(self.relative_pitch, "relative_pitch"),
        )
        object.__setattr__(self, "strength", normalized(self.strength, "strength", 0.0, 1.0))


@dataclass(frozen=True, slots=True)
class SpeechExpressionContext:
    expression_context_id: str
    source_context_revision: int
    internal_state_revision: int
    attention_revision: int | None
    source_refs: tuple[str, ...]
    axes: tuple[tuple[ExpressionAxis, float], ...]
    diagnostics: tuple[str, ...]
    updated_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.expression_context_id, "expression_context_id")
        require_revision(self.source_context_revision, "source_context_revision")
        require_revision(self.internal_state_revision, "internal_state_revision")
        require_revision(self.attention_revision, "attention_revision", optional=True)
        require_aware(self.updated_at, "updated_at")
        axes = tuple(self.axes)
        if len({name for name, _ in axes}) != len(axes) or any(
            not isinstance(name, ExpressionAxis) for name, _ in axes
        ):
            raise ValueError("expression axis は一意です")
        refs = tuple(self.source_refs)
        if any(not isinstance(reference, str) or not reference.strip() for reference in refs):
            raise ValueError("source_refs が不正です")
        object.__setattr__(
            self,
            "axes",
            tuple((name, normalized(value, name.value)) for name, value in axes),
        )
        object.__setattr__(self, "source_refs", refs)


@dataclass(frozen=True, slots=True)
class SpeechPerformanceConstraintView:
    constraint_id: str
    source_owner: str
    source_ref: str
    source_revision: int
    kind: str
    value: float

    def __post_init__(self) -> None:
        for name in ("constraint_id", "source_owner", "source_ref", "kind"):
            require_identifier(getattr(self, name), name)
        require_revision(self.source_revision, "source_revision")
        object.__setattr__(self, "value", normalized(self.value, "value"))


@dataclass(frozen=True, slots=True)
class SpeechPerformanceContextSnapshot:
    performance_request_id: str
    utterance: CharacterUtterance
    voice_style: CharacterVoiceStyleProfile | None
    expression: SpeechExpressionContext | None
    performance_constraints: tuple[SpeechPerformanceConstraintView, ...]
    source_context_revision: int
    goal_revision: int | None
    attention_revision: int | None
    captured_at: datetime
    trace_id: str

    def __post_init__(self) -> None:
        require_identifier(self.performance_request_id, "performance_request_id")
        require_identifier(self.trace_id, "trace_id")
        if not isinstance(self.utterance, CharacterUtterance):
            raise ValueError("utterance が不正です")
        if self.voice_style is not None and not isinstance(
            self.voice_style, CharacterVoiceStyleProfile
        ):
            raise ValueError("voice_style が不正です")
        if self.expression is not None and not isinstance(self.expression, SpeechExpressionContext):
            raise ValueError("expression が不正です")
        require_revision(self.source_context_revision, "source_context_revision")
        require_revision(self.goal_revision, "goal_revision", optional=True)
        require_revision(self.attention_revision, "attention_revision", optional=True)
        constraints = tuple(self.performance_constraints)
        if any(not isinstance(item, SpeechPerformanceConstraintView) for item in constraints):
            raise ValueError("performance_constraints が不正です")
        if len({item.constraint_id for item in constraints}) != len(constraints):
            raise ValueError("constraint_id は一意です")
        if self.expression is not None and (
            self.expression.source_context_revision != self.source_context_revision
            or self.expression.attention_revision != self.attention_revision
        ):
            raise ValueError("expression revision がsnapshotと一致しません")
        if utc_instant(self.captured_at) < utc_instant(self.utterance.committed_at):
            raise ValueError("snapshot はcommit済みutteranceより前にできません")
        object.__setattr__(self, "performance_constraints", constraints)
        require_aware(self.captured_at, "captured_at")


@dataclass(frozen=True, slots=True)
class SpeechPerformanceSegment:
    performance_segment_id: str
    utterance_segment_id: str
    boundary_strength: float
    pause_after_intent: float
    duration_bias: float
    emphasis_strength: float
    hesitation_strength: float
    local_intent_delta: PerformanceIntentDelta
    pitch_anchors: tuple[PitchAnchor, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.performance_segment_id, "performance_segment_id")
        require_identifier(self.utterance_segment_id, "utterance_segment_id")
        for name in (
            "boundary_strength",
            "pause_after_intent",
            "duration_bias",
            "emphasis_strength",
            "hesitation_strength",
        ):
            object.__setattr__(self, name, normalized(getattr(self, name), name, 0.0, 1.0))
        anchors = tuple(self.pitch_anchors)
        if any(
            left.position >= right.position
            for left, right in zip(anchors, anchors[1:], strict=False)
        ):
            raise ValueError("pitch_anchors はposition順です")
        object.__setattr__(self, "pitch_anchors", anchors)


@dataclass(frozen=True, slots=True)
class SpeechPerformancePlan:
    performance_plan_id: str
    utterance_id: str
    source_decision_id: str
    source_event_ids: tuple[str, ...]
    revisions: RevisionVector
    character_id: str
    character_schema_version: int
    character_definition_revision: int
    expression_context_id: str | None
    global_intent: PerformanceIntentVector
    segments: tuple[SpeechPerformanceSegment, ...]
    degraded: bool
    degradation_reasons: tuple[SpeechPerformanceDegradationReason, ...]
    policy_id: str
    policy_revision: int
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "performance_plan_id",
            "utterance_id",
            "source_decision_id",
            "character_id",
            "policy_id",
        ):
            require_identifier(getattr(self, name), name)
        require_revision(self.policy_revision, "policy_revision")
        require_aware(self.created_at, "created_at")
        source_event_ids = tuple(self.source_event_ids)
        if not source_event_ids or any(
            not isinstance(value, str) or not value.strip() for value in source_event_ids
        ):
            raise ValueError("source_event_ids が不正です")
        if len(source_event_ids) != len(set(source_event_ids)):
            raise ValueError("source_event_ids は一意です")
        object.__setattr__(self, "source_event_ids", source_event_ids)
        segments = tuple(self.segments)
        if any(not isinstance(item, SpeechPerformanceSegment) for item in segments):
            raise ValueError("segments が不正です")
        if not segments or len({item.utterance_segment_id for item in segments}) != len(segments):
            raise ValueError("segments はutterance segmentと一対一です")
        object.__setattr__(self, "segments", segments)
        if type(self.degraded) is not bool:
            raise ValueError("degraded が不正です")
        reasons = tuple(self.degradation_reasons)
        if any(not isinstance(item, SpeechPerformanceDegradationReason) for item in reasons):
            raise ValueError("degradation_reasons が不正です")
        if len(reasons) != len(set(reasons)) or self.degraded != bool(reasons):
            raise ValueError("degradation state が不整合です")
        object.__setattr__(self, "degradation_reasons", reasons)
