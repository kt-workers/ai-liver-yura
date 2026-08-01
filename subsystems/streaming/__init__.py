"""Core-independent Streaming Subsystem process shell."""

from subsystems.streaming.api import StreamingSubsystemApi
from subsystems.streaming.bootstrap import build_streaming_subsystem

__all__ = ["StreamingSubsystemApi", "build_streaming_subsystem"]
