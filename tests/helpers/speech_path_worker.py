"""実デバイス品質を主張せず、提示時間を持つprocess境界を再現する。"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from app.domain.speech_runtime.contracts import (
    SpeechPresentationCommand,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.domain.speech_runtime.presentation import PresentationAdapter


def build(kind: str, config: dict[str, Any]) -> PresentationAdapter:
    async def present(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        now = datetime.now(timezone.utc)
        started = SpeechPresentationReport(
            command.presentation_id,
            command.candidate_id,
            SpeechPresentationReportStatus.STARTED,
            command.modes,
            now,
            None,
            command.audio_ref,
            None,
        )
        yield started
        await asyncio.sleep(0.1)
        yield replace(
            started,
            status=SpeechPresentationReportStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )

    return present
