"""Build the Core-independent Streaming Subsystem object graph."""

from collections.abc import Callable
from datetime import datetime

from subsystems.streaming.adapters import FakeStreamingRuntime
from subsystems.streaming.api import StreamingSubsystemApi
from subsystems.streaming.application import StreamingSubsystemService


def build_streaming_subsystem(
    *,
    clock: Callable[[], datetime] | None = None,
) -> StreamingSubsystemApi:
    """Build a fresh process shell backed only by an in-memory Fake."""

    runtime = FakeStreamingRuntime() if clock is None else FakeStreamingRuntime(clock=clock)
    service = StreamingSubsystemService(runtime)
    return StreamingSubsystemApi(service)
