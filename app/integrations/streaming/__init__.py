"""Transport-neutral public contracts for the Streaming Subsystem."""

from app.integrations.streaming.client import StreamingClient
from app.integrations.streaming.composition import (
    CoreStreamingIntegration,
    CoreStreamingIntegrationConfig,
    create_core_streaming_integration,
)
from app.integrations.streaming.connection_state import (
    StreamingConnectionSnapshot,
    StreamingConnectionState,
    StreamingConnectionTracker,
)
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
from app.integrations.streaming.dependency_health import (
    DependencyKind,
    DependencyState,
    StreamingDependencyHealth,
    normalize_dependency_state,
)
from app.integrations.streaming.errors import (
    StreamingError,
    StreamingErrorCode,
    normalize_streaming_error_code,
)
from app.integrations.streaming.event_mapper import StreamingEventMapper
from app.integrations.streaming.event_receiver import StreamingEventReceiver
from app.integrations.streaming.events import (
    StreamingEventEnvelope,
    StreamingEventType,
    parse_streaming_event_type,
)
from app.integrations.streaming.gateway import StreamingGateway
from app.integrations.streaming.http_client import (
    HttpStreamingClient,
    StreamingHttpClientConfig,
)
from app.integrations.streaming.in_process_client import InProcessStreamingClient
from app.integrations.streaming.null_gateway import NullStreamingGateway
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
    "DependencyKind",
    "DependencyState",
    "UNKNOWN_ENUM_POLICY",
    "UNKNOWN_EVENT_TYPE_POLICY",
    "UNKNOWN_FIELD_POLICY",
    "StreamingApiVersion",
    "StreamingCapabilities",
    "StreamingCapability",
    "StreamingComment",
    "StreamingCursor",
    "StreamingDependencyHealth",
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
    "CoreStreamingIntegration",
    "CoreStreamingIntegrationConfig",
    "HttpStreamingClient",
    "InProcessStreamingClient",
    "NullStreamingGateway",
    "StreamingClient",
    "StreamingConnectionSnapshot",
    "StreamingConnectionState",
    "StreamingConnectionTracker",
    "StreamingEventMapper",
    "StreamingEventReceiver",
    "StreamingGateway",
    "StreamingHttpClientConfig",
    "create_core_streaming_integration",
    "is_streaming_api_compatible",
    "normalize_streaming_capabilities",
    "normalize_dependency_state",
    "normalize_streaming_error_code",
    "normalize_streaming_status",
    "parse_streaming_event_type",
]
