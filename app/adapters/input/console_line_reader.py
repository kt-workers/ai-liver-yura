from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import TextIO

BlockingInput = Callable[[str], str]


class ConsoleLineReader:
    """Event Loopを占有せずに標準入力から1行読む。"""

    def __init__(
        self,
        *,
        input_stream: TextIO | None = None,
        blocking_input: BlockingInput | None = None,
    ) -> None:
        self._input_stream = input_stream or sys.stdin
        self._blocking_input = blocking_input or input

    async def read(self, prompt: str = "> ") -> str | None:
        loop = asyncio.get_running_loop()
        try:
            file_descriptor = self._input_stream.fileno()
        except (AttributeError, OSError, ValueError):
            return await self._read_on_daemon_thread(loop, prompt)

        future: asyncio.Future[str | None] = loop.create_future()

        def on_readable() -> None:
            with suppress(Exception):
                loop.remove_reader(file_descriptor)
            if future.done():
                return
            try:
                value = self._input_stream.readline()
            except BaseException as error:
                future.set_exception(error)
                return
            future.set_result(None if value == "" else value)

        try:
            loop.add_reader(file_descriptor, on_readable)
        except (AttributeError, NotImplementedError, OSError, PermissionError):
            return await self._read_on_daemon_thread(loop, prompt)

        print(prompt, end="", flush=True)
        try:
            return await future
        finally:
            with suppress(Exception):
                loop.remove_reader(file_descriptor)

    async def _read_on_daemon_thread(
        self,
        loop: asyncio.AbstractEventLoop,
        prompt: str,
    ) -> str | None:
        """add_reader非対応環境では既定Executorを使わずdaemon threadで読む。"""

        future: asyncio.Future[str | None] = loop.create_future()

        def deliver_result(value: str | None) -> None:
            if not future.done():
                future.set_result(value)

        def deliver_error(error: BaseException) -> None:
            if not future.done():
                future.set_exception(error)

        def read_input() -> None:
            try:
                value = self._blocking_input(prompt)
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
            name="ConsoleLineReader",
            daemon=True,
        ).start()
        return await future
