"""Deprecated compatibility imports for Subsystem-owned Live Chat contracts."""

from subsystems.streaming.adapters.youtube.contracts import (
    LiveChatDeduplicationRepository,
    LiveChatMessageDto,
    LiveChatPageDto,
    YouTubeLiveChatReadPort,
)

__all__ = [
    "LiveChatDeduplicationRepository",
    "LiveChatMessageDto",
    "LiveChatPageDto",
    "YouTubeLiveChatReadPort",
]
