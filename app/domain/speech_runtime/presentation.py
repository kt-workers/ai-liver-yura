from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from .contracts import (
    SpeechPresentationCommand,
    SpeechPresentationCommitState,
    SpeechPresentationReport,
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
            async for report in adapter(command):
                await self._runtime.accept_report(report)
                terminal = report
            if terminal is None:
                raise ValueError("Presentation Adapterはreportを返す必要があります")
            return terminal

        generation = self._runtime.generation(candidate_id)
        self._tasks.start(CandidateTaskKey(candidate_id, generation, "presentation"), run())
        return command
