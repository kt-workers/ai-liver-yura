from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.runtime import EventPublisher, InputReceiver
from app.utils.trace import TraceLogger

InputProvider = Callable[[], Awaitable[str | None]]


class ConsoleInputReceiver(InputReceiver):
    """コンソール入力を USER_TEXT Event として投入する入力アダプタ。"""

    def __init__(self, input_provider: InputProvider | None = None) -> None:
        self._input_provider = input_provider or self._default_input_provider
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._trace_logger = TraceLogger()

    async def start(self, publish_event: EventPublisher) -> None:
        if self._task is not None and not self._task.done():
            return

        self._running = True
        self._task = asyncio.create_task(self._run(publish_event))

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def wait_until_stopped(self) -> None:
        task = self._task
        if task is None:
            return
        try:
            await task
        finally:
            if self._task is task:
                self._task = None

    async def _run(self, publish_event: EventPublisher) -> None:
        try:
            while self._running:
                try:
                    text = await self._input_provider()
                except UnicodeDecodeError as error:
                    self._trace_logger.warning(
                        "console_input_receiver:input_decode_failed",
                        encoding=error.encoding,
                        error_type=type(error).__name__,
                        start=error.start,
                        end=error.end,
                        reason=error.reason,
                        raw_input_length=len(error.object),
                        discarded=True,
                        retry=True,
                    )
                    print("入力を読み取れませんでした。もう一度入力してください。")
                    continue

                if text is None:
                    self._running = False
                    break

                stripped_text = text.strip()

                if stripped_text in ("exit", "quit"):
                    self._running = False
                    break

                if not stripped_text:
                    continue

                print()
                self._trace_logger.debug(
                    "console_input_receiver:user_text_received",
                    input_length=len(stripped_text),
                    source="console",
                )
                await publish_event(
                    AgentEvent(
                        event_type=AgentEventType.USER_TEXT,
                        payload={"text": stripped_text, "source": "console"},
                        authority=InputAuthority.ADMINISTRATOR,
                    )
                )
                await asyncio.sleep(0.01)
        finally:
            self._running = False

    async def _default_input_provider(self) -> str | None:
        """Event loopの既定Executorを占有せずに標準入力を待つ。"""

        loop = asyncio.get_running_loop()
        try:
            file_descriptor = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            return await self._read_input_on_daemon_thread(loop)

        future: asyncio.Future[str | None] = loop.create_future()

        def on_readable() -> None:
            loop.remove_reader(file_descriptor)
            if future.done():
                return
            try:
                value = sys.stdin.readline()
            except BaseException as error:
                future.set_exception(error)
                return
            future.set_result(None if value == "" else value)

        try:
            loop.add_reader(file_descriptor, on_readable)
        except (AttributeError, NotImplementedError, OSError, PermissionError):
            return await self._read_input_on_daemon_thread(loop)

        print("> ", end="", flush=True)
        try:
            return await future
        finally:
            loop.remove_reader(file_descriptor)

    @staticmethod
    async def _read_input_on_daemon_thread(
        loop: asyncio.AbstractEventLoop,
    ) -> str | None:
        """add_reader非対応環境用。既定Executorには登録しない。"""

        future: asyncio.Future[str | None] = loop.create_future()

        def deliver_result(value: str | None) -> None:
            if not future.done():
                future.set_result(value)

        def deliver_error(error: BaseException) -> None:
            if not future.done():
                future.set_exception(error)

        def read_input() -> None:
            try:
                value = input("> ")
            except EOFError:
                value = None
            except BaseException as error:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(deliver_error, error)
                return
            if not loop.is_closed():
                loop.call_soon_threadsafe(deliver_result, value)

        threading.Thread(
            target=read_input,
            name="ConsoleInputReceiver",
            daemon=True,
        ).start()
        return await future
