"""Transport-neutral public contracts for the Streaming Subsystem."""

from app.integrations.streaming.contracts import (
    StreamingCapabilities,
    StreamingCapability,
    StreamingComment,
    StreamingCursor,
    StreamingHealth,
    StreamingIdempotencyKey,
    StreamingStatus,
    normalize_streaming_capabilities,
    normalize_streaming_status,
)
from app.integrations.streaming.errors import (
    StreamingError,
    StreamingErrorCode,
    normalize_streaming_error_code,
)
from app.integrations.streaming.events import (
    StreamingEventEnvelope,
    StreamingEventType,
    parse_streaming_event_type,
)
from app.integrations.streaming.operations import (
    StreamingOperationRequest,
    StreamingOperationResult,
    StreamingOperationType,
)
from app.integrations.streaming.versioning import (
    CURRENT_STREAMING_API_VERSION,
    UNKNOWN_ENUM_POLICY,
    UNKNOWN_EVENT_TYPE_POLICY,
    UNKNOWN_FIELD_POLICY,
    StreamingApiVersion,
    is_streaming_api_compatible,
)

__all__ = [
    "CURRENT_STREAMING_API_VERSION",
    "UNKNOWN_ENUM_POLICY",
    "UNKNOWN_EVENT_TYPE_POLICY",
    "UNKNOWN_FIELD_POLICY",
    "StreamingApiVersion",
    "StreamingCapabilities",
    "StreamingCapability",
    "StreamingComment",
    "StreamingCursor",
    "StreamingError",
    "StreamingErrorCode",
    "StreamingEventEnvelope",
    "StreamingEventType",
    "StreamingHealth",
    "StreamingIdempotencyKey",
    "StreamingOperationRequest",
    "StreamingOperationResult",
    "StreamingOperationType",
    "StreamingStatus",
    "is_streaming_api_compatible",
    "normalize_streaming_capabilities",
    "normalize_streaming_error_code",
    "normalize_streaming_status",
    "parse_streaming_event_type",
]
