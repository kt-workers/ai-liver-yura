"""Deprecated alias; remove after Streaming Admin migration compatibility ends."""

from client.streaming_subsystem_event_stream_client import (
    StreamingSubsystemEventStreamClient as EventStreamClient,
)

__all__ = ["EventStreamClient"]
