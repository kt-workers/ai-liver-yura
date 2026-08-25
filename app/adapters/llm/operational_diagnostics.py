from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Protocol, runtime_checkable

from app.domain.contracts.common import require_aware, require_identifier


class LLMProviderOperationalFailureCategory(str, Enum):
    RATE_LIMITED_TRANSIENT = "rate_limited_transient"
    QUOTA_OR_BILLING_EXHAUSTED = "quota_or_billing_exhausted"
    REQUEST_TIMEOUT = "request_timeout"
    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    PROVIDER_SERVER_ERROR = "provider_server_error"
    PROVIDER_REQUEST_REJECTED = "provider_request_rejected"
    AUTHENTICATION_OR_PERMISSION_FAILED = "authentication_or_permission_failed"
    PROVIDER_PROTOCOL_ERROR = "provider_protocol_error"
    CANCELLED = "cancelled"
    UNKNOWN_PROVIDER_FAILURE = "unknown_provider_failure"


class LLMProviderSanitizedDetailCode(str, Enum):
    CLIENT_DEADLINE_EXCEEDED = "client_deadline_exceeded"
    CLIENT_TIMEOUT = "client_timeout"
    SDK_TIMEOUT = "sdk_timeout"
    SDK_CONNECTION = "sdk_connection"
    HTTP_408 = "http_408"
    HTTP_429_TRANSIENT = "http_429_transient"
    HTTP_429_QUOTA_OR_BILLING = "http_429_quota_or_billing"
    HTTP_429_UNCLASSIFIED = "http_429_unclassified"
    HTTP_5XX = "http_5xx"
    HTTP_AUTHENTICATION = "http_authentication"
    HTTP_PERMISSION = "http_permission"
    HTTP_REQUEST_REJECTED = "http_request_rejected"
    CANCELLED_BY_CALLER = "cancelled_by_caller"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LLMProviderOperationalDiagnostic:
    diagnostic_id: str
    logical_request_id: str
    role_id: str
    provider_id: str
    model_id: str | None
    category: LLMProviderOperationalFailureCategory
    http_status: int | None
    provider_request_id: str | None
    attempt_number: int
    retryable: bool
    occurred_at: datetime
    sanitized_detail_code: LLMProviderSanitizedDetailCode | None = None

    def __post_init__(self) -> None:
        for name in ("diagnostic_id", "logical_request_id", "role_id", "provider_id"):
            require_identifier(getattr(self, name), name)
        if self.model_id is not None:
            require_identifier(self.model_id, "model_id")
        if not isinstance(self.category, LLMProviderOperationalFailureCategory):
            raise ValueError("category が不正です")
        if self.http_status is not None and (
            type(self.http_status) is not int or not 100 <= self.http_status <= 599
        ):
            raise ValueError("http_status が不正です")
        if self.provider_request_id is not None:
            require_identifier(self.provider_request_id, "provider_request_id")
        if type(self.attempt_number) is not int or self.attempt_number < 0:
            raise ValueError("attempt_number が不正です")
        if type(self.retryable) is not bool:
            raise ValueError("retryable が不正です")
        require_aware(self.occurred_at, "occurred_at")
        if self.sanitized_detail_code is not None and not isinstance(
            self.sanitized_detail_code, LLMProviderSanitizedDetailCode
        ):
            raise ValueError("sanitized_detail_code が不正です")

    def fingerprint(self) -> tuple[str, str, str, int | None, str | None]:
        return (
            self.provider_id,
            "" if self.model_id is None else self.model_id,
            self.category.value,
            self.http_status,
            None
            if self.sanitized_detail_code is None
            else self.sanitized_detail_code.value,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "diagnostic_id": self.diagnostic_id,
            "logical_request_id": self.logical_request_id,
            "role_id": self.role_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "category": self.category.value,
            "http_status": self.http_status,
            "provider_request_id": self.provider_request_id,
            "attempt_number": self.attempt_number,
            "retryable": self.retryable,
            "occurred_at": self.occurred_at.isoformat(),
            "sanitized_detail_code": None
            if self.sanitized_detail_code is None
            else self.sanitized_detail_code.value,
        }


@runtime_checkable
class LLMProviderOperationalDiagnosticSink(Protocol):
    """非同期I/Oを呼出側へ返さず、即時受理だけを行うInfrastructure側の境界。"""

    def publish(self, diagnostic: LLMProviderOperationalDiagnostic) -> None: ...


@dataclass(frozen=True, slots=True)
class LLMProviderOperationalDiagnosticPublicationPolicy:
    minimum_interval_seconds: float = 60.0

    def __post_init__(self) -> None:
        if (
            type(self.minimum_interval_seconds) not in (int, float)
            or not isfinite(self.minimum_interval_seconds)
            or self.minimum_interval_seconds < 0
        ):
            raise ValueError("minimum_interval_seconds が不正です")


class LLMProviderOperationalDiagnosticPublisher:
    """診断sink失敗をProvider結果へ逆流させないbest-effort publication境界。"""

    def __init__(
        self,
        sink: LLMProviderOperationalDiagnosticSink | None,
        policy: LLMProviderOperationalDiagnosticPublicationPolicy,
        *,
        now: Callable[[], datetime],
    ) -> None:
        if sink is not None and not isinstance(sink, LLMProviderOperationalDiagnosticSink):
            raise ValueError("diagnostic sink が不正です")
        if not isinstance(policy, LLMProviderOperationalDiagnosticPublicationPolicy):
            raise ValueError("diagnostic publication policy が不正です")
        self._sink = sink
        self._policy = policy
        self._now = now
        self._last_published_at: dict[tuple[str, str, str, int | None, str | None], datetime] = {}

    def publish(self, diagnostic: LLMProviderOperationalDiagnostic) -> None:
        if self._sink is None:
            return
        fingerprint = diagnostic.fingerprint()
        previous = self._last_published_at.get(fingerprint)
        current = self._now()
        if (
            previous is not None
            and (current - previous).total_seconds() < self._policy.minimum_interval_seconds
        ):
            return
        self._last_published_at[fingerprint] = current
        try:
            self._sink.publish(diagnostic)
        except Exception:
            return
