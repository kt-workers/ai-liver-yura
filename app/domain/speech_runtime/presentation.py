from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from .contracts import (
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SpeechPresentationCommand,
    SpeechPresentationCommitState,
    SpeechPresentationReport,
)
from .execution import SpeechPresentationExecutionBoundary
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
        adapter: SpeechPresentationExecutionBoundary,
    ) -> SpeechPresentationCommand:
        command = await self._runtime.commit(candidate_id, state, presentation_id)

        generation = self._runtime.generation(candidate_id)
        policy = await self._runtime.presentation_timeout_policy(presentation_id)

        async def run() -> object:
            try:
                session = adapter.open(command, policy)
            except Exception:
                await self._runtime.fail_presentation_stream(candidate_id)
                raise
            pending: (
                asyncio.Task[tuple[SpeechPresentationReport, PreparedSpeechCandidate]] | None
            ) = None

            async def next_report() -> tuple[SpeechPresentationReport, PreparedSpeechCandidate]:
                report = await session.receive()
                if not isinstance(report, SpeechPresentationReport):
                    raise ValueError("Presentation Adapter reportの型が不正です")
                return report, await self._runtime.accept_report(report)

            try:
                while True:
                    remaining = await self._runtime.presentation_wait_seconds(
                        presentation_id, candidate_id, generation
                    )
                    if remaining is None:
                        return await self._runtime.candidate(candidate_id)
                    if pending is None:
                        pending = asyncio.create_task(next_report())
                    done, _ = await asyncio.wait((pending,), timeout=remaining)
                    if not done:
                        continue
                    try:
                        report, candidate = pending.result()
                    except StopAsyncIteration:
                        await self._runtime.fail_presentation_stream(candidate_id)
                        raise ValueError(
                            "Presentation Adapterはterminal reportを返す必要があります"
                        ) from None
                    pending = None
                    if candidate.lifecycle is not CandidateLifecycle.PRESENTING:
                        accepted = await self._runtime.presentation_reports(presentation_id)
                        return report if accepted and accepted[-1] == report else candidate
            except Exception:
                if (
                    await self._runtime.candidate(candidate_id)
                ).lifecycle is CandidateLifecycle.PRESENTING:
                    await self._runtime.fail_presentation_stream(candidate_id)
                raise
            finally:

                async def cleanup() -> None:
                    if pending is not None:
                        if not pending.done():
                            pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
                    await session.close()

                recovery = asyncio.create_task(cleanup())
                cancelled = False
                while True:
                    try:
                        await asyncio.shield(recovery)
                        break
                    except asyncio.CancelledError:
                        cancelled = True
                if cancelled:
                    raise asyncio.CancelledError

        self._tasks.start(CandidateTaskKey(candidate_id, generation, "presentation"), run())
        return command
