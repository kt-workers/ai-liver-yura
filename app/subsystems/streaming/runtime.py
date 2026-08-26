from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Protocol, cast

from app.subsystems.streaming.contracts import (
    StreamingCapabilityView,
    StreamingCommentEvent,
    StreamingCommentModerationState,
    StreamingCommentSignal,
    StreamingEffectState,
    StreamingExecutionReport,
    StreamingExecutionRequest,
    StreamingExecutionStatus,
    StreamingExternalObservation,
    StreamingObservationReconciliation,
    StreamingObservationSourceKind,
    StreamingSubsystemLifecycle,
)


class StreamingProviderPort(Protocol):
    async def execute(self, request: StreamingExecutionRequest) -> StreamingExecutionReport: ...


class StreamingCommentModerationPort(Protocol):
    async def moderate(self, comment: StreamingCommentEvent) -> StreamingCommentModerationState: ...


class StreamingSubsystemRuntime:
    """Coreをblockせず、現在generationにbindしたStreaming外部I/Oを扱う。"""

    def __init__(
        self,
        provider: StreamingProviderPort,
        capability: StreamingCapabilityView,
        *,
        moderator: StreamingCommentModerationPort | None = None,
        comment_limit: int = 64,
        reconnect_attempt_limit: int = 2,
        reconnect_delay_s: float = 0.05,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(comment_limit) is not int or comment_limit < 1:
            raise ValueError("comment_limit が不正です")
        if type(reconnect_attempt_limit) is not int or reconnect_attempt_limit < 1:
            raise ValueError("reconnect_attempt_limit が不正です")
        if type(reconnect_delay_s) not in {int, float} or not 0 < reconnect_delay_s <= 10:
            raise ValueError("reconnect_delay_s が不正です")
        self._provider = provider
        self._capability = capability
        self._moderator = moderator
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lifecycle = (
            StreamingSubsystemLifecycle.AVAILABLE
            if capability.available
            else StreamingSubsystemLifecycle.DEGRADED
        )
        self._observations: dict[
            tuple[StreamingObservationSourceKind, str], list[StreamingExternalObservation]
        ] = {}
        self._provider_generations: dict[str, int] = {}
        self._provider_observed_at: dict[str, datetime] = {}
        self._comments: deque[StreamingCommentEvent] = deque(maxlen=comment_limit)
        self._comment_signals: dict[str, StreamingCommentSignal] = {}
        self._dropped_comments = 0
        self._tasks: set[asyncio.Task[object]] = set()
        self._comment_worker: asyncio.Task[object] | None = None
        self._reconnect_attempt_limit = reconnect_attempt_limit
        self._reconnect_delay_s = float(reconnect_delay_s)
        self._stopping = False

    async def execute(self, request: StreamingExecutionRequest) -> StreamingExecutionReport:
        """provider invocation前後でcapability世代とeffect truthをfail-closedに確認する。"""
        now = self._now()
        if request.deadline_at is not None and request.deadline_at <= now:
            return self._report(
                request,
                StreamingExecutionStatus.FAILED,
                StreamingEffectState.NOT_APPLIED,
                now,
                "DEADLINE_BEFORE_START",
            )
        if not self._admitted(request):
            return self._report(
                request,
                StreamingExecutionStatus.PROVIDER_UNAVAILABLE,
                StreamingEffectState.NOT_APPLIED,
                now,
                "STALE_OR_UNAVAILABLE_CAPABILITY",
            )
        generation = self._capability.provider_generation
        try:
            provider_task = cast(
                asyncio.Task[StreamingExecutionReport],
                self._track(asyncio.create_task(self._provider.execute(request))),
            )
            if request.deadline_at is None:
                report = await provider_task
            else:
                remaining = (request.deadline_at - now).total_seconds()
                report = await asyncio.wait_for(provider_task, timeout=remaining)
        except asyncio.TimeoutError:
            return self._report(
                request,
                StreamingExecutionStatus.TIMED_OUT,
                StreamingEffectState.AMBIGUOUS,
                self._now(),
                "DEADLINE_DURING_EXECUTION",
            )
        except asyncio.CancelledError:
            return self._report(
                request,
                StreamingExecutionStatus.CANCELLED,
                StreamingEffectState.AMBIGUOUS,
                self._now(),
                "EXECUTION_CANCELLED",
            )
        except RuntimeError:
            self._lifecycle = StreamingSubsystemLifecycle.DEGRADED
            return self._report(
                request,
                StreamingExecutionStatus.PROVIDER_UNAVAILABLE,
                StreamingEffectState.UNKNOWN,
                self._now(),
                "PROVIDER_UNAVAILABLE",
            )
        if (
            report.execution_id != request.execution_id
            or report.operation is not request.operation
            or not self._admitted(request)
            or self._capability.provider_generation != generation
        ):
            return self._report(
                request,
                StreamingExecutionStatus.UNKNOWN_EFFECT,
                StreamingEffectState.AMBIGUOUS,
                self._now(),
                "STALE_CAPABILITY_AFTER_EXECUTION",
            )
        return report

    def update_capability(self, capability: StreamingCapabilityView) -> None:
        self._capability = capability
        self._lifecycle = (
            StreamingSubsystemLifecycle.AVAILABLE
            if capability.available
            else StreamingSubsystemLifecycle.DEGRADED
        )

    def accept_observation(self, observation: StreamingExternalObservation) -> bool:
        """providerとuserのprovenance履歴を別保持し、後続provider観測でのみreconcileする。"""
        if observation.source_kind is StreamingObservationSourceKind.PROVIDER_OBSERVATION:
            assert observation.provider_generation is not None
            current_generation = self._provider_generations.get(observation.source_ref)
            current_observed_at = self._provider_observed_at.get(observation.source_ref)
            if (
                current_generation is not None
                and (
                    observation.provider_generation < current_generation
                    or (
                        observation.provider_generation == current_generation
                        and current_observed_at is not None
                        and observation.observed_at <= current_observed_at
                    )
                )
            ):
                return False
            self._provider_generations[observation.source_ref] = observation.provider_generation
            self._provider_observed_at[observation.source_ref] = observation.observed_at
            observation = self._reconcile_user_reports(observation)
        else:
            observation = replace(
                observation,
                reconciliation=StreamingObservationReconciliation.UNRECONCILED,
            )
        key = (observation.source_kind, observation.source_ref)
        self._observations.setdefault(key, []).append(observation)
        return True

    def observation_history(
        self, source_kind: StreamingObservationSourceKind, source_ref: str
    ) -> tuple[StreamingExternalObservation, ...]:
        return tuple(self._observations.get((source_kind, source_ref), ()))

    async def ingest_comment(self, comment: StreamingCommentEvent) -> bool:
        """untrusted commentを正規化し、slow moderationをawaitせずbounded workerへ渡す。"""
        normalized = self._normalize_comment(comment)
        if len(self._comments) == self._comments.maxlen:
            self._dropped_comments += 1
        self._comments.append(normalized)
        if self._comment_worker is None or self._comment_worker.done():
            self._comment_worker = self._track(asyncio.create_task(self._run_comment_worker()))
        return True

    def drain_comment_signals(self) -> tuple[StreamingCommentSignal, ...]:
        signals = tuple(self._comment_signals.values())
        self._comment_signals.clear()
        return signals

    @property
    def dropped_comment_count(self) -> int:
        return self._dropped_comments

    @property
    def lifecycle(self) -> StreamingSubsystemLifecycle:
        return self._lifecycle

    def start_reconnect(self) -> bool:
        if self._stopping or self._lifecycle is StreamingSubsystemLifecycle.RECONNECTING:
            return False
        reconnect = getattr(self._provider, "reconnect", None)
        if not callable(reconnect):
            self._lifecycle = StreamingSubsystemLifecycle.DEGRADED
            return False
        self._lifecycle = StreamingSubsystemLifecycle.RECONNECTING
        reconnect_async = cast(Callable[[], Awaitable[bool]], reconnect)
        self._track(asyncio.create_task(self._run_reconnect(reconnect_async)))
        return True

    async def shutdown(self) -> None:
        self._stopping = True
        self._lifecycle = StreamingSubsystemLifecycle.STOPPING
        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._comment_worker = None
        self._lifecycle = StreamingSubsystemLifecycle.STOPPED

    @property
    def pending_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks)

    def _admitted(self, request: StreamingExecutionRequest) -> bool:
        capability = self._capability
        return (
            not self._stopping
            and self._lifecycle is StreamingSubsystemLifecycle.AVAILABLE
            and capability.available
            and request.capability_id == capability.capability_id
            and request.descriptor_revision == capability.descriptor_revision
            and request.operation in capability.operations
        )

    def _report(
        self,
        request: StreamingExecutionRequest,
        status: StreamingExecutionStatus,
        effect_state: StreamingEffectState,
        completed_at: datetime,
        diagnostic: str,
    ) -> StreamingExecutionReport:
        return StreamingExecutionReport(
            request.execution_id,
            request.operation,
            status,
            effect_state,
            completed_at,
            (),
            False,
            (diagnostic,),
        )

    def _reconcile_user_reports(
        self, provider: StreamingExternalObservation
    ) -> StreamingExternalObservation:
        user_key = (StreamingObservationSourceKind.USER_REPORT, provider.source_ref)
        user_history = self._observations.get(user_key, [])
        if not user_history:
            return provider
        reconciled: list[StreamingExternalObservation] = []
        reconciled_any = False
        for user in user_history:
            if user.observed_at > provider.observed_at:
                reconciled.append(user)
                continue
            reconciliation = (
                StreamingObservationReconciliation.CONFIRMED
                if user.state is provider.state
                else StreamingObservationReconciliation.CONTRADICTED
            )
            reconciled.append(replace(user, reconciliation=reconciliation))
            reconciled_any = True
        self._observations[user_key] = reconciled
        return replace(
            provider,
            reconciliation=(
                StreamingObservationReconciliation.CONFIRMED
                if reconciled_any
                else StreamingObservationReconciliation.UNRECONCILED
            ),
        )

    def _normalize_comment(self, comment: StreamingCommentEvent) -> StreamingCommentEvent:
        text = "".join(character for character in comment.text if character >= " ").strip()
        return replace(comment, text=text[:500])

    async def _run_comment_worker(self) -> None:
        while self._comments and not self._stopping:
            comment = self._comments.popleft()
            state = comment.moderation_state
            if state is StreamingCommentModerationState.PENDING:
                if self._moderator is None:
                    state = StreamingCommentModerationState.ACCEPTED
                else:
                    try:
                        state = await self._moderator.moderate(comment)
                    except RuntimeError:
                        self._dropped_comments += 1
                        continue
            if state is not StreamingCommentModerationState.ACCEPTED:
                continue
            existing = self._comment_signals.get(comment.source_channel_ref)
            if existing is not None:
                self._comment_signals[comment.source_channel_ref] = replace(
                    existing,
                    count=existing.count + 1,
                    generated_at=self._now(),
                )
                continue
            if len(self._comment_signals) == self._comments.maxlen:
                self._dropped_comments += 1
                continue
            self._comment_signals[comment.source_channel_ref] = StreamingCommentSignal(
                f"comment-signal:{comment.event_id}",
                comment.source_channel_ref,
                comment.event_id,
                1,
                self._now(),
            )

    async def _run_reconnect(self, reconnect: Callable[[], Awaitable[bool]]) -> None:
        for _ in range(self._reconnect_attempt_limit):
            if self._stopping:
                return
            try:
                if await reconnect():
                    # reconnect成功はprovider capability/descriptor snapshotの再取得を意味しない。
                    # 外部ownerがupdate_capability()で新snapshotを公開するまで実行を再開しない。
                    self._lifecycle = StreamingSubsystemLifecycle.DEGRADED
                    return
            except RuntimeError:
                pass
            await asyncio.sleep(self._reconnect_delay_s * (_ + 1))
        self._lifecycle = StreamingSubsystemLifecycle.DEGRADED

    def _track(self, task: asyncio.Task[object]) -> asyncio.Task[object]:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock がaware datetimeを返しません")
        return value
