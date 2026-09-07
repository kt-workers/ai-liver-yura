"""既存所有者の事実を読み、入力意味へ版付きの参照投影を供給する。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from typing import Protocol

from app.domain.activity_execution import ActivityExecutionAuthority, ActivityExecutionRecord
from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts.common import require_identifier
from app.domain.contracts.snapshots import (
    DEFAULT_SNAPSHOT_STABILIZATION_POLICY,
    SnapshotGenerationSample,
    SnapshotInvariantError,
    SnapshotReadCycle,
    SnapshotStabilizationPolicy,
    stabilize_snapshot,
)
from app.domain.goals import GoalCommitmentSnapshot, GoalContextView, build_goal_context_view
from app.domain.input_meaning import (
    InputMeaningFreshnessStamp,
    InputMeaningPolicy,
    ReferenceContext,
    ReferenceContextEntry,
    ReferenceContextKind,
)


class CoreGoalSnapshotReader(Protocol):
    def snapshot(self) -> GoalCommitmentSnapshot: ...


@dataclass(frozen=True, slots=True)
class CoreInputReferenceSnapshot:
    context: ReferenceContext
    goals: GoalContextView
    activities: tuple[ActivityExecutionRecord, ...]
    freshness: InputMeaningFreshnessStamp


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    goals: GoalContextView
    activities: tuple[ActivityExecutionRecord, ...]
    generations: tuple[SnapshotGenerationSample, ...]


def _sample(owner: str, revision: int, value: object) -> SnapshotGenerationSample:
    return SnapshotGenerationSample(owner, revision, sha256(repr(value).encode()).hexdigest())


class CoreInputReferenceContextBinding:
    """参照の投影世代だけを管理し、元の認知状態や判断は変更しない。"""

    def __init__(
        self,
        goals: CoreGoalSnapshotReader,
        activities: ActivityExecutionAuthority,
        meaning_policy: InputMeaningPolicy,
        bounds_policy: BrainOperationalBoundsPolicy,
        *,
        max_entries: int = 32,
        stabilization: SnapshotStabilizationPolicy = DEFAULT_SNAPSHOT_STABILIZATION_POLICY,
    ) -> None:
        if not isinstance(activities, ActivityExecutionAuthority):
            raise ValueError("活動参照には既存の実行事実所有者が必要です")
        if not isinstance(meaning_policy, InputMeaningPolicy):
            raise ValueError("入力意味の方針は当該構成世代の型付き設定が必要です")
        if not isinstance(bounds_policy, BrainOperationalBoundsPolicy):
            raise ValueError("目標参照には本体の上限方針が必要です")
        if not isinstance(stabilization, SnapshotStabilizationPolicy):
            raise ValueError("読取には型付きの版安定化方針が必要です")
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("参照数の上限は正の整数が必要です")
        self._goals = goals
        self._activities = activities
        self._meaning_policy = meaning_policy
        self._bounds = bounds_policy
        self._max_entries = max_entries
        self._stabilization = stabilization
        self._command_ids: tuple[str, ...] = ()
        self._sources: _SourceSnapshot | None = None
        self._published: CoreInputReferenceSnapshot | None = None
        self._lock = Lock()

    def set_activity_references(self, command_ids: tuple[str, ...]) -> None:
        """観測対象だけを明示し、実行要求や意味を生成しない。"""
        if not isinstance(command_ids, (tuple, list)):
            raise ValueError("活動参照は識別子の配列が必要です")
        values = tuple(command_ids)
        if len(values) > self._max_entries or len(set(values)) != len(values):
            raise ValueError("活動参照の重複または上限超過です")
        for command_id in values:
            require_identifier(command_id, "command_id")
        with self._lock:
            if any(self._activities.snapshot(value) is None for value in values):
                raise ValueError("所有者に存在しない活動は参照できません")
            self._command_ids = values

    def snapshot(self) -> CoreInputReferenceSnapshot:
        with self._lock:
            sources = stabilize_snapshot(self._stabilization, self._read_cycle)
            self._validate_history(sources)
            if sources == self._sources:
                assert self._published is not None
                return self._published
            revision = (
                1
                if self._published is None
                else self._published.context.source_context_revision + 1
            )
            entries = self._entries(sources, revision)
            context = ReferenceContext(revision, entries, self._max_entries)
            policy = self._meaning_policy.acceptance
            result = CoreInputReferenceSnapshot(
                context,
                sources.goals,
                sources.activities,
                InputMeaningFreshnessStamp(revision, policy.policy_id, policy.policy_revision),
            )
            self._sources, self._published = sources, result
            return result

    async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
        return self.snapshot().freshness

    def _read_sources(self) -> _SourceSnapshot:
        goals = build_goal_context_view(self._goals.snapshot(), bounds_policy=self._bounds)
        records: list[ActivityExecutionRecord] = []
        for command_id in self._command_ids:
            record = self._activities.snapshot(command_id)
            if record is None:
                raise ValueError("現在の活動記録を取得できません")
            records.append(record)
        generations = (_sample("goals", goals.goal_revision, goals),) + tuple(
            _sample("activity:" + record.result.command_id, record.record_revision, record)
            for record in records
        )
        return _SourceSnapshot(goals, tuple(records), generations)

    def _read_cycle(self) -> SnapshotReadCycle[_SourceSnapshot]:
        before, after = self._read_sources(), self._read_sources()
        return SnapshotReadCycle(
            before,
            before.generations,
            after.generations,
            self._stabilization.policy_id,
            self._stabilization.policy_revision,
        )

    def _validate_history(self, current: _SourceSnapshot) -> None:
        if self._sources is None:
            return
        previous = {sample.owner_id: sample for sample in self._sources.generations}
        for sample in current.generations:
            old = previous.get(sample.owner_id)
            if old is not None and (
                sample.revision < old.revision
                or (sample.revision == old.revision and sample != old)
            ):
                raise SnapshotInvariantError(
                    "元の所有者の版が退行したか、同じ版で内容が変わりました"
                )

    @staticmethod
    def _entries(sources: _SourceSnapshot, revision: int) -> tuple[ReferenceContextEntry, ...]:
        view = sources.goals
        goals = {
            item.goal_id: item
            for item in (*view.active_goals, *view.suspended_goals, *view.recently_changed_goals)
        }
        commitments = {
            item.commitment_id: item
            for item in (*view.commitments, *view.recently_changed_commitments)
        }
        values = [
            ReferenceContextEntry(
                "goal:" + key, ReferenceContextKind.GOAL_COMMITMENT, key, revision
            )
            for key in goals
        ] + [
            ReferenceContextEntry(
                "commitment:" + key, ReferenceContextKind.GOAL_COMMITMENT, key, revision
            )
            for key in commitments
        ]
        values.extend(
            ReferenceContextEntry(
                "activity:" + item.result.command_id,
                ReferenceContextKind.ACTUAL_EXECUTION_FACT,
                item.result.command_id,
                revision,
            )
            for item in sources.activities
        )
        return tuple(values)
