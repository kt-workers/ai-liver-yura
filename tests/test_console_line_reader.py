from __future__ import annotations

import asyncio

import pytest

from app.adapters.input.console_input_receiver import ConsoleInputReceiver
from app.adapters.input.console_line_reader import ConsoleLineReader
from app.domain.events import AgentEvent

pytestmark = pytest.mark.unit


class NoFileDescriptorStream:
    def fileno(self) -> int:
        raise OSError("no file descriptor")


@pytest.mark.asyncio
async def test_console_line_reader_uses_daemon_fallback_without_file_descriptor() -> None:
    prompts: list[str] = []
    reader = ConsoleLineReader(
        input_stream=NoFileDescriptorStream(),  # type: ignore[arg-type]
        blocking_input=lambda prompt: prompts.append(prompt) or "こんにちは",
    )

    value = await reader.read()

    assert value == "こんにちは"
    assert prompts == ["> "]


@pytest.mark.asyncio
async def test_console_line_reader_converts_eof_to_none() -> None:
    def raise_eof(prompt: str) -> str:
        del prompt
        raise EOFError

    reader = ConsoleLineReader(
        input_stream=NoFileDescriptorStream(),  # type: ignore[arg-type]
        blocking_input=raise_eof,
    )

    assert await reader.read() is None


@pytest.mark.asyncio
async def test_console_input_receiver_cancels_blocked_input_on_stop() -> None:
    started = asyncio.Event()

    async def blocked_input() -> str | None:
        started.set()
        await asyncio.Future()
        return None

    async def publish_event(event: AgentEvent) -> None:
        del event
        raise AssertionError("blocked input must not publish an event")

    receiver = ConsoleInputReceiver(input_provider=blocked_input)
    await receiver.start(publish_event)
    await started.wait()

    await asyncio.wait_for(receiver.stop(), timeout=0.5)


@pytest.mark.asyncio
async def test_console_input_receiver_can_restart_after_cancelled_stop() -> None:
    values = iter(("quit",))

    async def input_provider() -> str | None:
        return next(values, None)

    async def publish_event(event: AgentEvent) -> None:
        del event

    receiver = ConsoleInputReceiver(input_provider=input_provider)

    await receiver.start(publish_event)
    await receiver.wait_until_stopped()
    await receiver.start(publish_event)
    await receiver.wait_until_stopped()
