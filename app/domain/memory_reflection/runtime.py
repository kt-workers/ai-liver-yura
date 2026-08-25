"""#364のbounded background Reflection実行境界。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Protocol

from .authority import ReflectionCandidateAuthority
from .contracts import (
    MemoryCandidateProposal,
    ReflectionCandidateResult,
    ReflectionCandidateStatus,
    ReflectionContextSnapshot,
    ReflectionEventKind,
    ReflectionRunResult,
    ReflectionRunTelemetry,
    ReflectionSupportObservation,
)


class ReflectionProposalPort(Protocol):
    async def propose(
        self, context: ReflectionContextSnapshot
    ) -> tuple[MemoryCandidateProposal, ...]: ...


class ReflectionSupportPort(Protocol):
    async def observe(
        self,
        context: ReflectionContextSnapshot,
        proposal: MemoryCandidateProposal,
    ) -> ReflectionSupportObservation: ...


class ReflectionCoordinator:
    """background taskをbounded/coalescedにし、foregroundをawaitしない。"""

    def __init__(
        self,
        proposal_port: ReflectionProposalPort,
        support_port: ReflectionSupportPort,
        authority: ReflectionCandidateAuthority,
        *,
        max_concurrency: int = 2,
        max_pending_tasks: int = 64,
    ) -> None:
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 16:
            raise ValueError("max_concurrencyが不正です")
        if type(max_pending_tasks) is not int or not 1 <= max_pending_tasks <= 256:
            raise ValueError("max_pending_tasksが不正です")
        self._proposal_port = proposal_port
        self._support_port = support_port
        self._authority = authority
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_pending_tasks = max_pending_tasks
        self._tasks: dict[tuple[str, ...], asyncio.Task[ReflectionRunResult]] = {}
        self._coalesced_keys: set[tuple[str, ...]] = set()

    def submit(self, context: ReflectionContextSnapshot) -> asyncio.Task[ReflectionRunResult]:
        key = tuple(sorted(source.source_ref for source in context.primary_sources))
        existing = self._tasks.get(key)
        if existing is not None and not existing.done():
            self._coalesced_keys.add(key)
            return existing
        if self.pending_task_count >= self._max_pending_tasks:
            return asyncio.create_task(
                self._deferred_result(context),
                name=f"reflection-deferred:{context.reflection_id}",
            )
        task = asyncio.create_task(
            self._run(context, key),
            name=f"reflection:{context.reflection_id}",
        )
        self._tasks[key] = task
        return task

    async def cancel(self, context: ReflectionContextSnapshot) -> None:
        key = tuple(sorted(source.source_ref for source in context.primary_sources))
        task = self._tasks.get(key)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def shutdown(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    @property
    def pending_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks.values())

    async def _run(
        self,
        context: ReflectionContextSnapshot,
        key: tuple[str, ...],
    ) -> ReflectionRunResult:
        try:
            async with self._semaphore:
                events = [
                    ReflectionEventKind.TRIGGERED,
                    ReflectionEventKind.CONTEXT_CAPTURED,
                    ReflectionEventKind.PROPOSAL_STARTED,
                ]
                if key in self._coalesced_keys:
                    events.append(ReflectionEventKind.COALESCED)
                proposal_started = perf_counter()
                try:
                    proposals = await self._proposal_port.propose(context)
                except RuntimeError:
                    events.append(ReflectionEventKind.PROPOSAL_FAILED)
                    return ReflectionRunResult(
                        context.reflection_id,
                        (
                            ReflectionCandidateResult(
                                context.reflection_id,
                                ReflectionCandidateStatus.REFLECTION_PROVIDER_UNAVAILABLE,
                                None,
                                (),
                            ),
                        ),
                        tuple(key) if key in self._coalesced_keys else (),
                        telemetry=self._telemetry(
                            context,
                            events,
                            0,
                            (),
                            perf_counter() - proposal_started,
                            0.0,
                        ),
                    )
                events.append(ReflectionEventKind.PROPOSAL_COMPLETED)
                results, support_latency = await self._validate_all(context, proposals, events)
                events.extend(
                    ReflectionEventKind.CANDIDATE_ACCEPTED
                    if result.status is ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION
                    else ReflectionEventKind.CANDIDATE_REJECTED
                    for result in results
                )
                return ReflectionRunResult(
                    context.reflection_id,
                    tuple(results),
                    tuple(key) if key in self._coalesced_keys else (),
                    telemetry=self._telemetry(
                        context,
                        events,
                        len(proposals),
                        tuple(results),
                        perf_counter() - proposal_started - support_latency,
                        support_latency,
                    ),
                )
        finally:
            current = self._tasks.get(key)
            if current is asyncio.current_task():
                self._tasks.pop(key, None)
                self._coalesced_keys.discard(key)

    async def _deferred_result(
        self, context: ReflectionContextSnapshot
    ) -> ReflectionRunResult:
        return ReflectionRunResult(
            context.reflection_id,
            (
                ReflectionCandidateResult(
                    context.reflection_id,
                    ReflectionCandidateStatus.DEFERRED_QUEUE_PRESSURE,
                    None,
                    (),
                ),
            ),
            telemetry=ReflectionRunTelemetry(
                (
                    ReflectionEventKind.TRIGGERED,
                    ReflectionEventKind.DEFERRED,
                ),
                context.trigger.kind,
                len(context.primary_sources),
                context.estimated_tokens,
                0,
                0,
                ((ReflectionCandidateStatus.DEFERRED_QUEUE_PRESSURE, 1),),
                0.0,
                0.0,
            ),
        )

    async def _validate_all(
        self,
        context: ReflectionContextSnapshot,
        proposals: tuple[MemoryCandidateProposal, ...],
        events: list[ReflectionEventKind],
    ) -> tuple[list[ReflectionCandidateResult], float]:
        results: list[ReflectionCandidateResult] = []
        support_latency = 0.0
        for proposal in proposals:
            events.append(ReflectionEventKind.SUPPORT_STARTED)
            started = perf_counter()
            try:
                support = await self._support_port.observe(context, proposal)
            except RuntimeError:
                support_latency += perf_counter() - started
                events.append(ReflectionEventKind.SUPPORT_FAILED)
                results.append(self._authority.accept(context, proposal, None))
            else:
                support_latency += perf_counter() - started
                events.append(ReflectionEventKind.SUPPORT_COMPLETED)
                results.append(self._authority.accept(context, proposal, support))
        return results, support_latency

    @staticmethod
    def _telemetry(
        context: ReflectionContextSnapshot,
        events: list[ReflectionEventKind],
        proposal_count: int,
        results: tuple[ReflectionCandidateResult, ...],
        proposal_latency: float,
        support_latency: float,
    ) -> ReflectionRunTelemetry:
        rejected_counts: dict[ReflectionCandidateStatus, int] = {}
        for result in results:
            if result.status is not ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION:
                rejected_counts[result.status] = rejected_counts.get(result.status, 0) + 1
        return ReflectionRunTelemetry(
            tuple(events),
            context.trigger.kind,
            len(context.primary_sources),
            context.estimated_tokens,
            proposal_count,
            sum(
                result.status is ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION
                for result in results
            ),
            tuple(rejected_counts.items()),
            max(0.0, proposal_latency * 1_000),
            max(0.0, support_latency * 1_000),
        )


BackgroundContinuation = Callable[[Awaitable[ReflectionRunResult]], None]
