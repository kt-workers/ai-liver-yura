from client.streaming_subsystem_api_client import (
    StreamingSubsystemApiClient,
    StreamingSubsystemApiError,
)
from client.streaming_subsystem_event_stream_client import (
    StreamingSubsystemEventStreamClient,
)

# Deprecated aliases for existing callers; remove in K.
CoreApiClient = StreamingSubsystemApiClient
CoreApiError = StreamingSubsystemApiError
EventStreamClient = StreamingSubsystemEventStreamClient

__all__ = [
    "StreamingSubsystemApiClient",
    "StreamingSubsystemApiError",
    "StreamingSubsystemEventStreamClient",
    "CoreApiClient",
    "CoreApiError",
    "EventStreamClient",
]
