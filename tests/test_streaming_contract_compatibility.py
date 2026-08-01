from __future__ import annotations

import operator

import pytest

from app.integrations.streaming import (
    CURRENT_STREAMING_API_VERSION,
    UNKNOWN_ENUM_POLICY,
    UNKNOWN_EVENT_TYPE_POLICY,
    UNKNOWN_FIELD_POLICY,
    StreamingApiVersion,
    StreamingCapability,
    StreamingError,
    StreamingErrorCode,
    StreamingEventType,
    StreamingStatus,
    is_streaming_api_compatible,
    normalize_streaming_capabilities,
    normalize_streaming_error_code,
    normalize_streaming_status,
    parse_streaming_event_type,
)


def test_current_api_version_is_defined_once_as_version_1_0() -> None:
    assert CURRENT_STREAMING_API_VERSION == StreamingApiVersion(major=1, minor=0)
    assert str(CURRENT_STREAMING_API_VERSION) == "1.0"


def test_minor_versions_are_compatible_within_the_same_major() -> None:
    version_1_0 = StreamingApiVersion(major=1, minor=0)
    version_1_9 = StreamingApiVersion(major=1, minor=9)

    assert is_streaming_api_compatible(version_1_0, version_1_9)
    assert is_streaming_api_compatible(version_1_9, version_1_0)


def test_different_major_versions_are_not_compatible() -> None:
    assert not is_streaming_api_compatible(
        StreamingApiVersion(major=1, minor=9),
        StreamingApiVersion(major=2, minor=0),
    )


def test_compatibility_policies_are_stable() -> None:
    assert UNKNOWN_FIELD_POLICY == "ignore"
    assert UNKNOWN_EVENT_TYPE_POLICY == "ignore"
    assert UNKNOWN_ENUM_POLICY == "safe_fallback"


def test_unknown_status_uses_degraded_fallback() -> None:
    assert normalize_streaming_status("future_status") is StreamingStatus.DEGRADED


def test_unknown_capabilities_are_not_treated_as_available() -> None:
    assert normalize_streaming_capabilities(
        ["prepare", "future_adapter_capability"],
    ) == frozenset({StreamingCapability.PREPARE})


def test_unknown_event_type_is_ignored() -> None:
    assert parse_streaming_event_type("future_event") is None
    assert (
        parse_streaming_event_type("status_changed")
        is StreamingEventType.STATUS_CHANGED
    )


def test_unknown_error_code_uses_stable_fallback() -> None:
    assert (
        normalize_streaming_error_code("future_error")
        is StreamingErrorCode.UNKNOWN
    )


def test_error_details_are_defensively_copied_and_immutable() -> None:
    details: dict[str, object] = {"attempt": 1}
    error = StreamingError(
        code=StreamingErrorCode.TIMEOUT,
        message="timed out",
        retryable=True,
        details=details,
    )

    details["attempt"] = 2

    assert error.details == {"attempt": 1}
    with pytest.raises(TypeError):
        operator.setitem(error.details, "attempt", 2)
