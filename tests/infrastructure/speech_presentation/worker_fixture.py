"""実worker内だけで使う故障注入Adapter。実デバイス品質の証拠にはしない。"""

import asyncio
import os
import signal
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from app.domain.speech_runtime.contracts import SpeechPresentationCommand, SpeechPresentationReport
from app.domain.speech_runtime.contracts import SpeechPresentationReportStatus as Status
from app.domain.speech_runtime.presentation import PresentationAdapter


def build(kind: str, config: dict[str, Any]) -> PresentationAdapter:
    async def adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        if config.get("pid_file"):
            with open(config["pid_file"], "w") as file:
                file.write(str(os.getpid()))
        now = datetime.now(timezone.utc)
        report = SpeechPresentationReport(
            command.presentation_id,
            command.candidate_id,
            Status.STARTED,
            command.modes,
            now,
            None,
            command.audio_ref,
            None,
        )
        if kind == "exit_before":
            os._exit(9)
        if kind == "failed_before":
            yield replace(
                report, status=Status.FAILED_BEFORE_START, started_at=None, completed_at=now
            )
            return
        if kind in ("hang", "ignore_terminate", "hang_before"):
            if kind == "ignore_terminate":
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            if kind != "hang_before":
                yield report
            while True:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    continue
        yield report
        if kind == "exit_after":
            os._exit(9)
        if kind == "missing":
            return
        if kind == "wrong_identity":
            yield replace(report, candidate_id="wrong", status=Status.COMPLETED, completed_at=now)
            return
        if kind == "stdout_noise":
            print("SDKの人間向けlog")
            os.write(1, b"SDK log\n")
        yield replace(
            report,
            status=Status.FAILED_AFTER_START if kind == "failed_after" else Status.COMPLETED,
            completed_at=now,
        )

    return adapter
