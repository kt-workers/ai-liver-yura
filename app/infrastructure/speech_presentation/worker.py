"""明示moduleとして起動する子worker。importだけでは実行しない。"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import threading
from typing import Any, BinaryIO

from app.domain.speech_runtime.contracts import SpeechPresentationReportStatus

from .codec import MAX_MESSAGE_BYTES, decode, encode, parse_command, report_payload


async def execute(payload: dict[str, Any], writer: BinaryIO) -> None:
    command = parse_command(payload["command"])
    factory = getattr(importlib.import_module(payload["factory_module"]), payload["factory_name"])
    adapter = factory(payload["adapter_kind"], payload["configuration"])
    async for report in adapter(command):
        writer.write(encode("report", command, report_payload(report)))
        writer.flush()
        if report.status is not SpeechPresentationReportStatus.STARTED:
            return


async def run(payload: dict[str, Any], writer: BinaryIO) -> None:
    task = asyncio.create_task(execute(payload, writer))
    loop = asyncio.get_running_loop()

    def stop_on_eof() -> None:
        while os.read(sys.stdin.fileno(), 1):
            pass
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            pass

    # stdin EOF待機は子のdaemon threadのみ。正常終了をthread待機へ従属させない。
    threading.Thread(target=stop_on_eof, daemon=True).start()
    await task


def main() -> None:
    # fdレベルでもSDKの標準出力をprotocolから隔離する。
    with os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0) as writer:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        try:
            line = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1)
            packet = decode(line, "command")
            payload = packet["payload"]
            if set(payload) != {
                "command",
                "adapter_kind",
                "factory_module",
                "factory_name",
                "configuration",
            }:
                raise ValueError("worker要求が不正です")
            command = parse_command(payload["command"])
            decode(line, "command", command)
            asyncio.run(run(payload, writer))
        except BaseException:
            # 例外や設定・SDK応答はprotocolへ反射しない。
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
