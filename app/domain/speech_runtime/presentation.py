from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from .contracts import (
    CandidateLifecycle,
    SpeechPresentationCommand,
    SpeechPresentationCommitState,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from .runtime import SpeechRuntime
from .tasks import CandidateTaskKey, CandidateTaskRegistry

PresentationAdapter = Callable[[SpeechPresentationCommand], AsyncIterator[SpeechPresentationReport]]


class SpeechPresentationExecutor:
    """commit後のAdapter I/Oをcandidate局所taskとして実行する。"""

    def __init__(self, runtime: SpeechRuntime, tasks: CandidateTaskRegistry) -> None:
        self._runtime = runtime
        self._tasks = tasks

    async def commit_and_present(
        self,
        *,
        candidate_id: str,
        state: SpeechPresentationCommitState,
        presentation_id: str,
        adapter: PresentationAdapter,
    ) -> SpeechPresentationCommand:
        command = await self._runtime.commit(candidate_id, state, presentation_id)

        async def run() -> object:
            terminal: SpeechPresentationReport | None = None
            try:
                async for report in adapter(command):
                    await self._runtime.accept_report(report)
                    terminal = report
                if terminal is None or terminal.status not in {
                    SpeechPresentationReportStatus.COMPLETED,
                    SpeechPresentationReportStatus.FAILED_BEFORE_START,
                    SpeechPresentationReportStatus.FAILED_AFTER_START,
                    SpeechPresentationReportStatus.INTERRUPTED,
                }:
                    await self._runtime.fail_presentation_stream(candidate_id)
                    raise ValueError("Presentation Adapterはterminal reportを返す必要があります")
                return terminal
            except Exception:
                if (
                    await self._runtime.candidate(candidate_id)
                ).lifecycle is CandidateLifecycle.PRESENTING:
                    await self._runtime.fail_presentation_stream(candidate_id)
                raise

        generation = self._runtime.generation(candidate_id)
        self._tasks.start(CandidateTaskKey(candidate_id, generation, "presentation"), run())
        return command
