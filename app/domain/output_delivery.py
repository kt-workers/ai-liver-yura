from __future__ import annotations

OPTIONAL_OUTPUT_DEGRADED_PREFIX = "optional_output_degraded:"


def optional_output_degraded_error(channel: str, error: str) -> str:
    normalized_channel = channel.strip() or "unknown"
    normalized_error = error.strip() or "unknown_error"
    return (
        f"{OPTIONAL_OUTPUT_DEGRADED_PREFIX}"
        f"channel={normalized_channel};error={normalized_error}"
    )


def is_optional_output_degraded(error: str | None) -> bool:
    return isinstance(error, str) and error.startswith(
        OPTIONAL_OUTPUT_DEGRADED_PREFIX
    )
