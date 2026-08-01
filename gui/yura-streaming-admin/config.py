"""Configuration for the standalone streaming admin web process."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class StreamingSubsystemAdminConfig:
    base_url: str = "http://127.0.0.1:8781"
    token: str | None = field(default=None, repr=False)
    timeout_seconds: float = 10.0
    operator: str = "operator"

    def __post_init__(self) -> None:
        normalized = self.base_url.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "base_url", normalized)

    @classmethod
    def from_environment(cls) -> StreamingSubsystemAdminConfig:
        def value(new: str, old: str, default: str | None = None) -> str | None:
            return os.getenv(new, os.getenv(old, default))

        return cls(
            base_url=str(
                value(
                    "STREAMING_SUBSYSTEM_ADMIN_API_URL",
                    "AI_LIVER_ADMIN_API_URL",
                    "http://127.0.0.1:8781",
                )
            ),
            token=value(
                "STREAMING_SUBSYSTEM_ADMIN_API_TOKEN",
                "AI_LIVER_ADMIN_API_TOKEN",
            ),
            timeout_seconds=float(
                str(
                    value(
                        "STREAMING_SUBSYSTEM_ADMIN_API_TIMEOUT",
                        "AI_LIVER_ADMIN_API_TIMEOUT",
                        "10",
                    )
                )
            ),
            operator=str(
                value(
                    "STREAMING_SUBSYSTEM_ADMIN_OPERATOR",
                    "AI_LIVER_ADMIN_OPERATOR",
                    "operator",
                )
            ),
        )


# Deprecated environment/config import compatibility; remove in K.
AdminClientConfig = StreamingSubsystemAdminConfig
