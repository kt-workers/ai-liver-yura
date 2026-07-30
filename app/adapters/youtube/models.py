"""Deprecated compatibility imports for Subsystem-owned YouTube mappers."""

from subsystems.streaming.adapters.youtube.mapper import (
    map_broadcast,
    map_broadcast_status,
    map_stream_health,
    map_stream_status,
    parse_datetime,
)

__all__ = [
    "map_broadcast",
    "map_broadcast_status",
    "map_stream_health",
    "map_stream_status",
    "parse_datetime",
]
