from __future__ import annotations

from typing import cast

import pytest

from app.adapters.tts import (
    TTSMappingDimension,
    TTSMappingMonotonicity,
    TTSParameterMappingRule,
    TTSPerformanceMappingPolicy,
    TTSProviderOperationalPolicy,
    TTSUnitParameterMappingRule,
    validate_tts_policy_bundle,
)
from app.runtime.lifecycle import DependencyRetryPolicy


def signed_rule(
    *,
    monotonicity: TTSMappingMonotonicity = TTSMappingMonotonicity.INCREASING,
) -> TTSParameterMappingRule:
    values = (-2.0, 0.0, 4.0)
    if monotonicity is TTSMappingMonotonicity.DECREASING:
        values = (4.0, 0.0, -2.0)
    return TTSParameterMappingRule(
        TTSMappingDimension.PACE,
        "speedScale",
        values[0],
        values[1],
        values[2],
        monotonicity,
    )


def test_signed_mapping_exact_endpoints_and_intermediates() -> None:
    rule = signed_rule()
    assert rule.project(-1.0) == -2.0
    assert rule.project(0.0) == 0.0
    assert rule.project(1.0) == 4.0
    assert rule.project(-0.5) == -1.0
    assert rule.project(0.5) == 2.0


def test_decreasing_mapping_preserves_neutral_and_direction() -> None:
    rule = signed_rule(monotonicity=TTSMappingMonotonicity.DECREASING)
    assert rule.project(-1.0) == 4.0
    assert rule.project(0.0) == 0.0
    assert rule.project(1.0) == -2.0
    assert rule.project(-0.5) == 2.0
    assert rule.project(0.5) == -1.0


def test_signed_mapping_rejects_out_of_range_bool_nan_and_infinity() -> None:
    rule = signed_rule()
    for invalid in (-1.0001, 1.0001, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            rule.project(invalid)
    with pytest.raises(ValueError):
        rule.project(cast(float, True))


def test_mapping_rule_rejects_invalid_monotonic_provider_order() -> None:
    with pytest.raises(ValueError):
        TTSParameterMappingRule(
            TTSMappingDimension.PACE,
            "speedScale",
            1.0,
            0.0,
            2.0,
            TTSMappingMonotonicity.INCREASING,
        )
    with pytest.raises(ValueError):
        TTSParameterMappingRule(
            TTSMappingDimension.PACE,
            "speedScale",
            -1.0,
            0.0,
            1.0,
            TTSMappingMonotonicity.DECREASING,
        )


def test_unit_mapping_uses_explicit_neutral_without_hidden_signed_conversion() -> None:
    centered = TTSUnitParameterMappingRule(
        TTSMappingDimension.DURATION_BIAS,
        "durationBias",
        0.0,
        0.5,
        1.0,
        -100.0,
        0.0,
        100.0,
        TTSMappingMonotonicity.INCREASING,
    )
    assert centered.project(0.0) == -100.0
    assert centered.project(0.5) == 0.0
    assert centered.project(1.0) == 100.0
    assert centered.project(0.75) == 50.0

    pause = TTSUnitParameterMappingRule(
        TTSMappingDimension.PHRASE_PAUSE,
        "pauseMs",
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        1000.0,
        TTSMappingMonotonicity.INCREASING,
    )
    assert pause.project(0.0) == 0.0
    assert pause.project(0.6) == 600.0
    assert pause.project(1.0) == 1000.0


def test_mapping_policy_rejects_duplicate_dimension_and_parameter() -> None:
    first = signed_rule()
    duplicate_dimension = TTSParameterMappingRule(
        TTSMappingDimension.PACE,
        "otherSpeed",
        -1.0,
        0.0,
        1.0,
        TTSMappingMonotonicity.INCREASING,
    )
    with pytest.raises(ValueError, match="dimension"):
        TTSPerformanceMappingPolicy(
            "mapping",
            1,
            "fake",
            1,
            (first, duplicate_dimension),
            (),
        )
    duplicate_parameter = TTSParameterMappingRule(
        TTSMappingDimension.PITCH_CENTER,
        "speedScale",
        -1.0,
        0.0,
        1.0,
        TTSMappingMonotonicity.INCREASING,
    )
    with pytest.raises(ValueError, match="provider_parameter"):
        TTSPerformanceMappingPolicy(
            "mapping",
            1,
            "fake",
            1,
            (first, duplicate_parameter),
            (),
        )


def test_operational_policy_and_bundle_are_strict_and_same_provider_generation() -> None:
    mapping = TTSPerformanceMappingPolicy("mapping", 1, "fake", 1, (signed_rule(),), ())
    operational = TTSProviderOperationalPolicy("tts", 1, "fake", 1, 1.0, 1, 1)
    retry = DependencyRetryPolicy("retry", 1, "fake", True, 1, 0.1, 2.0, 1.0, 1.0)
    validate_tts_policy_bundle(mapping, operational, retry)

    with pytest.raises(ValueError):
        TTSProviderOperationalPolicy("tts", 1, "fake", 1, cast(float, True), 1, 1)
    with pytest.raises(ValueError):
        TTSProviderOperationalPolicy("tts", 1, "fake", 1, float("nan"), 1, 1)
    with pytest.raises(ValueError):
        TTSProviderOperationalPolicy("tts", 1, "fake", 1, 1.0, cast(int, True), 1)
    with pytest.raises(ValueError, match="provider generation"):
        validate_tts_policy_bundle(
            mapping,
            TTSProviderOperationalPolicy("tts", 1, "other", 1, 1.0, 1, 1),
            retry,
        )
