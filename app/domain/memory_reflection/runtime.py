"""#364のbounded background Reflection実行境界。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from hashlib import sha256
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
from .operational import (
    ReflectionOperationalError,
    ReflectionOperationalFailureCode,
    ReflectionOperationalPolicy,
    validate_reflection_context_bounds,
    validate_reflection_proposals_bounds,
    validate_reflection_support_bounds,
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


LiveReflectionContextReader = Callable[
    [ReflectionContextSnapshot], ReflectionContextSnapshot | None
]


class ReflectionCoordinator:
    """background taskをbounded/coalescedにし、foregroundをawaitしない。"""

    def __init__(
        self,
        proposal_port: ReflectionProposalPort,
        support_port: ReflectionSupportPort,
        authority: ReflectionCandidateAuthority,
        *,
        operational_policy: ReflectionOperationalPolicy,
        max_pending_tasks: int,
        lane_max_concurrency: int | None = None,
        live_context: LiveReflectionContextReader | None = None,
    ) -> None:
        if not isinstance(operational_policy, ReflectionOperationalPolicy):
            raise ValueError("Reflection operational policy が必要です")
        if type(max_pending_tasks) is not int or max_pending_tasks < 1:
            raise ValueError("max_pending_tasksが不正です")
        if lane_max_concurrency is not None and (
            type(lane_max_concurrency) is not int or lane_max_concurrency < 1
        ):
            raise ValueError("lane_max_concurrencyが不正です")
        self._proposal_port = proposal_port
        self._support_port = support_port
        self._authority = authority
        self._operational_policy = operational_policy
        self._max_pending_tasks = max_pending_tasks
        self._lane_max_concurrency = lane_max_concurrency
        self._live_context = live_context or (lambda context: context)
        self._tasks: dict[str, asyncio.Task[ReflectionRunResult]] = {}
        self._coalesced_keys: set[str] = set()
        self._active_reflections = 0
        self._concurrency_condition = asyncio.Condition()

    @property
    def operational_policy(self) -> ReflectionOperationalPolicy:
        return self._operational_policy

    @property
    def effective_max_concurrency(self) -> int:
        if self._lane_max_concurrency is None:
            return self._operational_policy.max_concurrent_reflections
        return min(
            self._operational_policy.max_concurrent_reflections,
            self._lane_max_concurrency,
        )

    @property
    def active_reflection_count(self) -> int:
        return self._active_reflections

    async def update_operational_policy(self, policy: ReflectionOperationalPolicy) -> None:
        if not isinstance(policy, ReflectionOperationalPolicy):
            raise ValueError("Reflection operational policy が必要です")
        async with self._concurrency_condition:
            self._operational_policy = policy
            self._concurrency_condition.notify_all()

    def submit(self, context: ReflectionContextSnapshot) -> asyncio.Task[ReflectionRunResult]:
        validate_reflection_context_bounds(context, self._operational_policy)
        key = self._context_key(context)
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
        key = self._context_key(context)
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
        key: str,
    ) -> ReflectionRunResult:
        acquired = False
        try:
            await self._acquire_concurrency_slot()
            acquired = True
            events = [
                ReflectionEventKind.TRIGGERED,
                ReflectionEventKind.CONTEXT_CAPTURED,
            ]
            if key in self._coalesced_keys:
                events.append(ReflectionEventKind.COALESCED)
            if not self._policy_matches_context(context):
                return self._single_failure_result(
                    context,
                    key,
                    events,
                    ReflectionCandidateStatus.REJECTED_STALE,
                    proposal_count=0,
                    proposal_latency=0.0,
                )
            events.append(ReflectionEventKind.PROPOSAL_STARTED)
            proposal_started = perf_counter()
            try:
                proposals = await self._proposal_port.propose(context)
            except RuntimeError:
                events.append(ReflectionEventKind.PROPOSAL_FAILED)
                self._append_coalesced_event(events, key)
                return self._single_failure_result(
                    context,
                    key,
                    events,
                    ReflectionCandidateStatus.REFLECTION_PROVIDER_UNAVAILABLE,
                    proposal_count=0,
                    proposal_latency=perf_counter() - proposal_started,
                )
            events.append(ReflectionEventKind.PROPOSAL_COMPLETED)
            if not self._policy_matches_context(context):
                return self._single_failure_result(
                    context,
                    key,
                    events,
                    ReflectionCandidateStatus.REJECTED_STALE,
                    proposal_count=len(proposals),
                    proposal_latency=perf_counter() - proposal_started,
                )
            try:
                validate_reflection_proposals_bounds(proposals, self._operational_policy)
            except ReflectionOperationalError:
                return self._single_failure_result(
                    context,
                    key,
                    events,
                    ReflectionCandidateStatus.REJECTED_POLICY,
                    proposal_count=len(proposals),
                    proposal_latency=perf_counter() - proposal_started,
                )
            live_context, live_failure = self._validated_live_context(context)
            if live_failure is not None:
                results = [
                    self._candidate_failure_result(proposal, live_failure)
                    for proposal in proposals
                ]
                support_latency = 0.0
            else:
                assert live_context is not None
                results, support_latency = await self._validate_all(
                    live_context,
                    proposals,
                    events,
                )
            self._append_coalesced_event(events, key)
            if any(
                result.status is ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION
                for result in results
            ):
                events.append(ReflectionEventKind.CANDIDATE_ACCEPTED)
            if any(
                result.status is not ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION
                for result in results
            ):
                events.append(ReflectionEventKind.CANDIDATE_REJECTED)
            return ReflectionRunResult(
                context.reflection_id,
                tuple(results),
                self._source_refs(context) if key in self._coalesced_keys else (),
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
            if acquired:
                await self._release_concurrency_slot()
            current = self._tasks.get(key)
            if current is asyncio.current_task():
                self._tasks.pop(key, None)
                self._coalesced_keys.discard(key)

    async def _acquire_concurrency_slot(self) -> None:
        async with self._concurrency_condition:
            await self._concurrency_condition.wait_for(
                lambda: self._active_reflections < self.effective_max_concurrency
            )
            self._active_reflections += 1

    async def _release_concurrency_slot(self) -> None:
        async with self._concurrency_condition:
            if self._active_reflections < 1:
                raise ValueError("Reflection concurrency leaseが存在しません")
            self._active_reflections -= 1
            self._concurrency_condition.notify_all()

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
        for index, proposal in enumerate(proposals):
            if not self._policy_matches_context(context):
                results.extend(self._stale_result(item) for item in proposals[index:])
                break
            if ReflectionEventKind.SUPPORT_STARTED not in events:
                events.append(ReflectionEventKind.SUPPORT_STARTED)
            started = perf_counter()
            try:
                support = await self._support_port.observe(context, proposal)
            except RuntimeError:
                support_latency += perf_counter() - started
                if ReflectionEventKind.SUPPORT_FAILED not in events:
                    events.append(ReflectionEventKind.SUPPORT_FAILED)
                if not self._policy_matches_context(context):
                    results.append(self._stale_result(proposal))
                    continue
                live_context, live_failure = self._validated_live_context(context)
                if live_failure is not None:
                    results.append(
                        self._candidate_failure_result(proposal, live_failure)
                    )
                else:
                    assert live_context is not None
                    results.append(self._authority.accept(live_context, proposal, None))
            else:
                support_latency += perf_counter() - started
                if ReflectionEventKind.SUPPORT_COMPLETED not in events:
                    events.append(ReflectionEventKind.SUPPORT_COMPLETED)
                if not self._policy_matches_context(context):
                    results.append(self._stale_result(proposal))
                    continue
                try:
                    validate_reflection_support_bounds(support, self._operational_policy)
                except ReflectionOperationalError:
                    results.append(self._policy_result(proposal))
                    continue
                live_context, live_failure = self._validated_live_context(context)
                if live_failure is not None:
                    results.append(
                        self._candidate_failure_result(proposal, live_failure)
                    )
                else:
                    assert live_context is not None
                    results.append(self._authority.accept(live_context, proposal, support))
        return results, support_latency

    def _validated_live_context(
        self,
        captured_context: ReflectionContextSnapshot,
    ) -> tuple[
        ReflectionContextSnapshot | None,
        ReflectionCandidateStatus | None,
    ]:
        live_context = self._live_context(captured_context)
        if live_context is None:
            return None, ReflectionCandidateStatus.REJECTED_STALE
        try:
            validate_reflection_context_bounds(live_context, self._operational_policy)
        except ReflectionOperationalError as error:
            status = (
                ReflectionCandidateStatus.REJECTED_STALE
                if error.code is ReflectionOperationalFailureCode.POLICY_STALE
                else ReflectionCandidateStatus.REJECTED_POLICY
            )
            return None, status
        return live_context, None

    def _policy_matches_context(self, context: ReflectionContextSnapshot) -> bool:
        return self._operational_policy.same_generation(
            context.operational_policy_id,
            context.operational_policy_revision,
        )

    def _single_failure_result(
        self,
        context: ReflectionContextSnapshot,
        key: str,
        events: list[ReflectionEventKind],
        status: ReflectionCandidateStatus,
        *,
        proposal_count: int,
        proposal_latency: float,
    ) -> ReflectionRunResult:
        if ReflectionEventKind.CANDIDATE_REJECTED not in events:
            events.append(ReflectionEventKind.CANDIDATE_REJECTED)
        self._append_coalesced_event(events, key)
        result = ReflectionCandidateResult(
            context.reflection_id,
            status,
            None,
            (),
        )
        return ReflectionRunResult(
            context.reflection_id,
            (result,),
            self._source_refs(context) if key in self._coalesced_keys else (),
            telemetry=self._telemetry(
                context,
                events,
                proposal_count,
                (result,),
                proposal_latency,
                0.0,
            ),
        )

    @staticmethod
    def _candidate_failure_result(
        proposal: MemoryCandidateProposal,
        status: ReflectionCandidateStatus,
    ) -> ReflectionCandidateResult:
        if status not in {
            ReflectionCandidateStatus.REJECTED_STALE,
            ReflectionCandidateStatus.REJECTED_POLICY,
        }:
            raise ValueError("Reflection operational failure statusが不正です")
        return ReflectionCandidateResult(
            proposal.proposal_id,
            status,
            None,
            proposal.source_refs,
        )

    @staticmethod
    def _source_refs(context: ReflectionContextSnapshot) -> tuple[str, ...]:
        return tuple(sorted(source.source_ref for source in context.primary_sources))

    @staticmethod
    def _stale_result(proposal: MemoryCandidateProposal) -> ReflectionCandidateResult:
        return ReflectionCoordinator._candidate_failure_result(
            proposal,
            ReflectionCandidateStatus.REJECTED_STALE,
        )

    @staticmethod
    def _policy_result(proposal: MemoryCandidateProposal) -> ReflectionCandidateResult:
        return ReflectionCoordinator._candidate_failure_result(
            proposal,
            ReflectionCandidateStatus.REJECTED_POLICY,
        )

    def _append_coalesced_event(self, events: list[ReflectionEventKind], key: str) -> None:
        if key in self._coalesced_keys and ReflectionEventKind.COALESCED not in events:
            events.append(ReflectionEventKind.COALESCED)

    @staticmethod
    def _context_key(context: ReflectionContextSnapshot) -> str:
        encoded = json.dumps(
            context.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        return sha256(encoded.encode()).hexdigest()

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
