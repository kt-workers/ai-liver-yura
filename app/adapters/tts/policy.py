from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from app.domain.contracts.common import require_identifier, require_revision
from app.runtime.lifecycle import DependencyRetryPolicy


class TTSMappingMonotonicity(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"


class TTSMappingDimension(str, Enum):
    PACE = "pace"
    ENERGY = "energy"
    PITCH_CENTER = "pitch_center"
    PITCH_RANGE = "pitch_range"
    LOUDNESS = "loudness"
    SOFTNESS = "softness"
    BREATHINESS = "breathiness"
    TENSION = "tension"
    EXPRESSIVENESS = "expressiveness"
    BOUNDARY_STRENGTH = "boundary_strength"
    PHRASE_PAUSE = "phrase_pause"
    DURATION_BIAS = "duration_bias"
    EMPHASIS_STRENGTH = "emphasis_strength"
    HESITATION_STRENGTH = "hesitation_strength"
    PITCH_ANCHOR = "pitch_anchor"


def _finite(value: object, name: str) -> float:
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{name}はfinite numberでなければなりません")
    return float(value)


def _validate_provider_order(
    minimum: float,
    neutral: float,
    maximum: float,
    monotonicity: TTSMappingMonotonicity,
) -> None:
    if monotonicity is TTSMappingMonotonicity.INCREASING:
        if not minimum <= neutral <= maximum:
            raise ValueError("INCREASING ruleはprovider_min <= neutral <= maxが必要です")
    elif monotonicity is TTSMappingMonotonicity.DECREASING:
        if not minimum >= neutral >= maximum:
            raise ValueError("DECREASING ruleはprovider_min >= neutral >= maxが必要です")
    else:
        raise ValueError("mapping monotonicityが不正です")


@dataclass(frozen=True, slots=True)
class TTSParameterMappingRule:
    dimension: TTSMappingDimension
    provider_parameter: str
    provider_min: float
    provider_neutral: float
    provider_max: float
    monotonicity: TTSMappingMonotonicity

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, TTSMappingDimension):
            raise ValueError("mapping dimensionが不正です")
        require_identifier(self.provider_parameter, "provider_parameter")
        minimum = _finite(self.provider_min, "provider_min")
        neutral = _finite(self.provider_neutral, "provider_neutral")
        maximum = _finite(self.provider_max, "provider_max")
        _validate_provider_order(minimum, neutral, maximum, self.monotonicity)
        object.__setattr__(self, "provider_min", minimum)
        object.__setattr__(self, "provider_neutral", neutral)
        object.__setattr__(self, "provider_max", maximum)

    def project(self, normalized: float) -> float:
        value = _finite(normalized, "normalized")
        if not -1.0 <= value <= 1.0:
            raise ValueError("normalizedは[-1,1]でなければなりません")
        if value <= 0.0:
            t = value + 1.0
            return self.provider_min + t * (self.provider_neutral - self.provider_min)
        return self.provider_neutral + value * (self.provider_max - self.provider_neutral)


@dataclass(frozen=True, slots=True)
class TTSUnitParameterMappingRule:
    dimension: TTSMappingDimension
    provider_parameter: str
    source_min: float
    source_neutral: float
    source_max: float
    provider_min: float
    provider_neutral: float
    provider_max: float
    monotonicity: TTSMappingMonotonicity

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, TTSMappingDimension):
            raise ValueError("mapping dimensionが不正です")
        require_identifier(self.provider_parameter, "provider_parameter")
        source_min = _finite(self.source_min, "source_min")
        source_neutral = _finite(self.source_neutral, "source_neutral")
        source_max = _finite(self.source_max, "source_max")
        if source_min != 0.0 or source_max != 1.0:
            raise ValueError("unit ruleのsource rangeは0..1でなければなりません")
        if not source_min <= source_neutral <= source_max:
            raise ValueError("source_neutralがsource range外です")
        minimum = _finite(self.provider_min, "provider_min")
        neutral = _finite(self.provider_neutral, "provider_neutral")
        maximum = _finite(self.provider_max, "provider_max")
        _validate_provider_order(minimum, neutral, maximum, self.monotonicity)
        object.__setattr__(self, "source_min", source_min)
        object.__setattr__(self, "source_neutral", source_neutral)
        object.__setattr__(self, "source_max", source_max)
        object.__setattr__(self, "provider_min", minimum)
        object.__setattr__(self, "provider_neutral", neutral)
        object.__setattr__(self, "provider_max", maximum)

    def project(self, value: float) -> float:
        source = _finite(value, "source value")
        if not self.source_min <= source <= self.source_max:
            raise ValueError("source valueが0..1の範囲外です")
        if source <= self.source_neutral:
            if self.source_neutral == self.source_min:
                return self.provider_neutral
            t = (source - self.source_min) / (self.source_neutral - self.source_min)
            return self.provider_min + t * (self.provider_neutral - self.provider_min)
        if self.source_neutral == self.source_max:
            return self.provider_neutral
        t = (source - self.source_neutral) / (self.source_max - self.source_neutral)
        return self.provider_neutral + t * (self.provider_max - self.provider_neutral)


@dataclass(frozen=True, slots=True)
class TTSPerformanceMappingPolicy:
    mapping_id: str
    mapping_revision: int
    provider_id: str
    provider_revision: int
    signed_rules: tuple[TTSParameterMappingRule, ...]
    unit_rules: tuple[TTSUnitParameterMappingRule, ...]

    def __post_init__(self) -> None:
        require_identifier(self.mapping_id, "mapping_id")
        require_revision(self.mapping_revision, "mapping_revision")
        require_identifier(self.provider_id, "provider_id")
        require_revision(self.provider_revision, "provider_revision")
        signed = tuple(self.signed_rules)
        unit = tuple(self.unit_rules)
        if any(not isinstance(item, TTSParameterMappingRule) for item in signed):
            raise ValueError("signed_rulesが不正です")
        if any(not isinstance(item, TTSUnitParameterMappingRule) for item in unit):
            raise ValueError("unit_rulesが不正です")
        dimensions = [item.dimension for item in signed] + [item.dimension for item in unit]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("mapping dimensionは重複できません")
        parameters = [item.provider_parameter for item in signed] + [
            item.provider_parameter for item in unit
        ]
        if len(parameters) != len(set(parameters)):
            raise ValueError("provider_parameterは重複できません")
        object.__setattr__(self, "signed_rules", signed)
        object.__setattr__(self, "unit_rules", unit)

    def signed_rule_for(self, dimension: TTSMappingDimension) -> TTSParameterMappingRule | None:
        return next((item for item in self.signed_rules if item.dimension is dimension), None)

    def unit_rule_for(self, dimension: TTSMappingDimension) -> TTSUnitParameterMappingRule | None:
        return next((item for item in self.unit_rules if item.dimension is dimension), None)


@dataclass(frozen=True, slots=True)
class TTSProviderOperationalPolicy:
    policy_id: str
    policy_revision: int
    provider_id: str
    provider_revision: int
    timeout_seconds: float
    max_foreground_synthesis: int
    max_speculative_synthesis: int

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "tts operational policy_id")
        require_revision(self.policy_revision, "tts operational policy_revision")
        require_identifier(self.provider_id, "provider_id")
        require_revision(self.provider_revision, "provider_revision")
        timeout = _finite(self.timeout_seconds, "timeout_seconds")
        if timeout <= 0:
            raise ValueError("timeout_secondsは正でなければなりません")
        for value, name in (
            (self.max_foreground_synthesis, "max_foreground_synthesis"),
            (self.max_speculative_synthesis, "max_speculative_synthesis"),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name}は1以上のintでなければなりません")
        object.__setattr__(self, "timeout_seconds", timeout)


def validate_tts_policy_bundle(
    mapping: TTSPerformanceMappingPolicy,
    operational: TTSProviderOperationalPolicy,
    retry: DependencyRetryPolicy,
) -> None:
    if not isinstance(mapping, TTSPerformanceMappingPolicy):
        raise ValueError("TTS mapping policyが必要です")
    if not isinstance(operational, TTSProviderOperationalPolicy):
        raise ValueError("TTS operational policyが必要です")
    if not isinstance(retry, DependencyRetryPolicy):
        raise ValueError("Dependency retry policyが必要です")
    if not (
        mapping.provider_id == operational.provider_id == retry.dependency_id
        and mapping.provider_revision == operational.provider_revision
    ):
        raise ValueError("TTS policy bundleのprovider generationが一致しません")
