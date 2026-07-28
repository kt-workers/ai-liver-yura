from __future__ import annotations

from app.config.errors import ConfigError
from app.config.strict import (
    optional_bool,
    optional_int,
    optional_mapping,
    optional_number,
    optional_string,
    reject_unknown_keys,
    require_mapping,
)
from app.domain.emotions import (
    EmotionAppraisalCircuitBreakerSettings,
    EmotionAppraisalHistorySettings,
    EmotionAppraisalMode,
    EmotionAppraisalSettings,
)


def load_emotion_appraisal_settings(value: object) -> EmotionAppraisalSettings:
    """emotion_appraisal mappingをAppConfig用の型付き設定へ変換する。"""

    if value is None or value == "":
        return EmotionAppraisalSettings()

    config = require_mapping(value, "emotion_appraisal")
    reject_unknown_keys(
        config,
        {
            "enabled",
            "mode",
            "llm_role",
            "timeout_seconds",
            "confidence_threshold",
            "weak_confidence_threshold",
            "fallback",
            "max_concurrency",
            "cache_ttl_seconds",
            "cache_max_entries",
            "circuit_breaker",
            "history",
        },
        "emotion_appraisal",
    )

    circuit = optional_mapping(config, "circuit_breaker", "emotion_appraisal")
    history = optional_mapping(config, "history", "emotion_appraisal")
    reject_unknown_keys(
        circuit,
        {"failure_threshold", "recovery_seconds"},
        "emotion_appraisal.circuit_breaker",
    )
    reject_unknown_keys(
        history,
        {"max_entries", "retention_seconds", "min_effective_delta"},
        "emotion_appraisal.history",
    )

    enabled = optional_bool(config, "enabled", "emotion_appraisal", default=True)
    configured_mode = optional_string(config, "mode", "emotion_appraisal") or "hybrid"
    try:
        mode = EmotionAppraisalMode(configured_mode)
    except ValueError as error:
        raise ConfigError(
            path="emotion_appraisal.mode",
            expected="disabled, rule_based, llm, or hybrid",
            actual=configured_mode,
        ) from error
    if not enabled:
        mode = EmotionAppraisalMode.DISABLED

    timeout_seconds = optional_number(
        config, "timeout_seconds", "emotion_appraisal", default=2.5
    )
    confidence_threshold = optional_number(
        config, "confidence_threshold", "emotion_appraisal", default=0.55
    )
    weak_confidence_threshold = optional_number(
        config,
        "weak_confidence_threshold",
        "emotion_appraisal",
        default=0.40,
    )
    max_concurrency = optional_int(
        config, "max_concurrency", "emotion_appraisal", default=2
    )
    cache_ttl_seconds = optional_number(
        config, "cache_ttl_seconds", "emotion_appraisal", default=20.0
    )
    cache_max_entries = optional_int(
        config, "cache_max_entries", "emotion_appraisal", default=256
    )
    failure_threshold = optional_int(
        circuit,
        "failure_threshold",
        "emotion_appraisal.circuit_breaker",
        default=5,
    )
    recovery_seconds = optional_number(
        circuit,
        "recovery_seconds",
        "emotion_appraisal.circuit_breaker",
        default=30.0,
    )
    max_entries = optional_int(
        history,
        "max_entries",
        "emotion_appraisal.history",
        default=200,
    )
    retention_seconds = optional_number(
        history,
        "retention_seconds",
        "emotion_appraisal.history",
        default=7200.0,
    )
    min_effective_delta = optional_number(
        history,
        "min_effective_delta",
        "emotion_appraisal.history",
        default=0.02,
    )

    assert timeout_seconds is not None
    assert confidence_threshold is not None
    assert weak_confidence_threshold is not None
    assert max_concurrency is not None
    assert cache_ttl_seconds is not None
    assert cache_max_entries is not None
    assert failure_threshold is not None
    assert recovery_seconds is not None
    assert max_entries is not None
    assert retention_seconds is not None
    assert min_effective_delta is not None

    try:
        return EmotionAppraisalSettings(
            enabled=enabled,
            mode=mode,
            llm_role=(
                optional_string(config, "llm_role", "emotion_appraisal")
                or "emotion_appraisal"
            ),
            timeout_seconds=timeout_seconds,
            confidence_threshold=confidence_threshold,
            weak_confidence_threshold=weak_confidence_threshold,
            fallback=(
                optional_string(config, "fallback", "emotion_appraisal")
                or "rule_based"
            ),
            max_concurrency=max_concurrency,
            cache_ttl_seconds=cache_ttl_seconds,
            cache_max_entries=cache_max_entries,
            circuit_breaker=EmotionAppraisalCircuitBreakerSettings(
                failure_threshold=failure_threshold,
                recovery_seconds=recovery_seconds,
            ),
            history=EmotionAppraisalHistorySettings(
                max_entries=max_entries,
                retention_seconds=retention_seconds,
                min_effective_delta=min_effective_delta,
            ),
        )
    except ValueError as error:
        raise ConfigError(
            path="emotion_appraisal",
            expected="valid emotion appraisal settings",
            actual=str(error),
        ) from error
