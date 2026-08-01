"""Deprecated aliases; canonical client targets Streaming Subsystem Admin API."""

from client.streaming_subsystem_api_client import (
    StreamingSubsystemApiClient as CoreApiClient,
)
from client.streaming_subsystem_api_client import (
    StreamingSubsystemApiError as CoreApiError,
)

__all__ = ["CoreApiClient", "CoreApiError"]
