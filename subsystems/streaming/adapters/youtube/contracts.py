"""YouTube-specific internal contracts owned by Streaming Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from app.integrations.streaming import StreamingComment, StreamingCursor


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class YouTubeAuthenticationStatus(str, Enum):
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHENTICATION_IN_PROGRESS = "authentication_in_progress"
    AUTHENTICATED = "authenticated"
    AUTHENTICATION_FAILED = "authentication_failed"


@dataclass(frozen=True, slots=True)
class YouTubeAuthenticationState:
    status: YouTubeAuthenticationStatus
    failure_reason: str | None = None
    observed_at: datetime = field(default_factory=utc_now)


class YouTubeBroadcastStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    TESTING = "testing"
    LIVE = "live"
    COMPLETE = "complete"
    REVOKED = "revoked"
    FAILED = "failed"
    UNKNOWN = "unknown"


class YouTubeStreamStatus(str, Enum):
    UNKNOWN = "unknown"
    INACTIVE = "inactive"
    READY = "ready"
    ACTIVE = "active"
    ERROR = "error"


class YouTubeLiveChatStatus(str, Enum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class YouTubeLiveChatSnapshot:
    status: YouTubeLiveChatStatus
    live_chat_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class YouTubeBroadcastSummary:
    broadcast_id: str
    title: str
    scheduled_start_at: datetime | None = None
    privacy_status: str = "private"
    lifecycle_status: str = "ready"
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    live_chat_id: str | None = None
    bound_stream_id: str | None = None
    selectable: bool = True


@dataclass(frozen=True, slots=True)
class YouTubeStreamSnapshot:
    stream_id: str
    status: str
    bound: bool
    live_chat_id: str | None = None
    ingestion_type: str | None = None
    health_status: str = "unknown"


@dataclass(frozen=True, slots=True)
class LiveChatMessageDto:
    message_id: str
    kind: str
    snippet: dict[str, Any]
    author: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LiveChatPageDto:
    messages: tuple[LiveChatMessageDto, ...]
    next_page_token: str | None
    polling_interval_ms: int


@dataclass(frozen=True, slots=True)
class StreamingCommentPage:
    comments: tuple[StreamingComment, ...]
    cursor: StreamingCursor | None
    polling_interval_ms: int


class YouTubeLiveChatReadPort(Protocol):
    @property
    def adapter_type(self) -> str: ...

    async def get_live_chat_status(self, live_chat_id: str) -> str: ...

    async def list_messages(
        self,
        live_chat_id: str,
        page_token: str | None,
        max_results: int,
    ) -> LiveChatPageDto: ...


class LiveChatDeduplicationRepository(Protocol):
    def check_and_mark(self, session_id: str, key: str) -> bool:
        """Return True only for the first occurrence."""


class YouTubePreparationPort(Protocol):
    @property
    def adapter_type(self) -> str: ...

    async def get_authentication_state(self) -> YouTubeAuthenticationState: ...

    async def authenticate(self) -> YouTubeAuthenticationState: ...

    async def list_broadcasts(self) -> tuple[YouTubeBroadcastSummary, ...]: ...

    async def check_authentication(self) -> bool: ...

    async def resolve_broadcast(
        self,
        broadcast_id: str,
    ) -> YouTubeBroadcastSummary: ...

    async def resolve_bound_stream(
        self,
        broadcast_id: str,
    ) -> YouTubeStreamSnapshot: ...

    async def get_stream_status(self, stream_id: str) -> str: ...

    async def get_broadcast_status(self, broadcast_id: str) -> str: ...

    async def get_live_chat_id(self, broadcast_id: str) -> str | None: ...

    async def get_live_chat_availability(
        self,
        broadcast_id: str,
    ) -> YouTubeLiveChatSnapshot: ...

    async def health_check(self) -> bool: ...


class YouTubeStreamingControlPort(Protocol):
    @property
    def adapter_type(self) -> str: ...

    async def get_stream_status(self, stream_id: str) -> str: ...

    async def transition_broadcast_to_live(self, broadcast_id: str) -> None: ...

    async def transition_broadcast_to_complete(self, broadcast_id: str) -> None: ...

    async def get_broadcast_status(self, broadcast_id: str) -> str: ...
