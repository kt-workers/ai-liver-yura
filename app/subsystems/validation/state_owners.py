"""局所的な状態所有者を使い、目標・約束の更新と注意の引渡しを検証する。"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import cast

from app.domain.attention import (
    AttentionCoordinator,
    AttentionIngressSignal,
    AttentionSchedulingPolicy,
    AttentionTurnStore,
    ExecutiveTriggerEligibility,
)
from app.domain.contracts.common import JsonValue, freeze_json, require_revision
from app.domain.executive import CommittedExecutiveDecision
from app.domain.goals import (
    GoalCommitmentCommitResult,
    GoalCommitmentSnapshot,
    GoalCommitmentStore,
    GoalLifecycleProjectionFact,
)
from app.usecases.attention import CommitmentAttentionProjector, GoalAttentionProjector
from app.usecases.attention.projectors import AttentionProjectionEnvelope

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .runtime import LabTarget, RunContext


def _encode(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return dict(value)
    if (
        is_dataclass(value)
        and not isinstance(value, type)
        and type(value).__module__.startswith(("app.domain.goals.", "app.domain.attention."))
    ):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    raise ValueError("目標・約束・注意の公開契約以外は投影できません")


def _project(value: object) -> JsonValue:
    return freeze_json(
        cast(JsonValue, json.loads(json.dumps(value, default=_encode, allow_nan=False)))
    )


@dataclass(frozen=True)
class GoalAttentionLabSettings:
    policy: AttentionSchedulingPolicy
    source_context_revisions: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.policy, AttentionSchedulingPolicy):
            raise ValueError("注意の割当方針が不正です")
        revisions = tuple(self.source_context_revisions)
        for revision in revisions:
            require_revision(revision, "source_context_revision")
        object.__setattr__(self, "source_context_revisions", revisions)

    def typed_inputs(self) -> JsonValue:
        return _project(
            {"policy": self.policy, "source_context_revisions": self.source_context_revisions}
        )


@dataclass(frozen=True)
class GoalCommitmentLabCase:
    fixture: ValidationFixture
    initial: GoalCommitmentSnapshot
    decisions: tuple[CommittedExecutiveDecision, ...]
    attention: GoalAttentionLabSettings | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.initial, GoalCommitmentSnapshot):
            raise ValueError("目標・約束の初期状態が不正です")
        if not self.decisions or any(
            not isinstance(x, CommittedExecutiveDecision) for x in self.decisions
        ):
            raise ValueError("採用済みの実行判断が必要です")
        object.__setattr__(self, "decisions", tuple(self.decisions))
        if self.attention is not None:
            if not isinstance(self.attention, GoalAttentionLabSettings):
                raise ValueError("注意への接続設定が不正です")
            if len(self.attention.source_context_revisions) != len(self.decisions):
                raise ValueError("各更新の注意への引渡し時点の文脈版が必要です")

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "initial": self.initial.to_dict(),
                "decisions": [x.to_dict() for x in self.decisions],
                "attention": None if self.attention is None else self.attention.typed_inputs(),
            }
        )


def goal_commitment_target(
    cases: tuple[GoalCommitmentLabCase, ...],
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("目標・約束の検証条件は重複できません")

    adjacent = {case.attention is not None for case in cases}
    if len(adjacent) > 1:
        raise ValueError("単独検証と注意への隣接検証は別の対象登録にしてください")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        owner = GoalCommitmentStore(case.initial)
        commits: list[JsonValue] = []
        attention_steps: list[JsonValue] = []
        enqueued: list[ExecutiveTriggerEligibility] = []
        store = None if case.attention is None else AttentionTurnStore(case.attention.policy)
        coordinator = None if store is None else AttentionCoordinator(store, store, enqueued.append)
        for index, decision in enumerate(case.decisions):

            async def apply(
                item: CommittedExecutiveDecision = decision,
            ) -> GoalCommitmentCommitResult:
                return owner.apply(item)

            committed = await context.invoke_product("goals.apply", apply)
            commits.append(_project(committed))
            if case.attention is not None and store is not None and coordinator is not None:
                for fact in committed.lifecycle_facts:
                    source_context_revision = case.attention.source_context_revisions[index]
                    if isinstance(fact, GoalLifecycleProjectionFact):
                        signal = GoalAttentionProjector().project(
                            AttentionProjectionEnvelope(fact, source_context_revision)
                        )
                    else:
                        signal = CommitmentAttentionProjector().project(
                            AttentionProjectionEnvelope(fact, source_context_revision)
                        )

                    async def handle(
                        signal: AttentionIngressSignal = signal,
                        goal_revision: int = committed.snapshot.revision,
                    ) -> ExecutiveTriggerEligibility | None:
                        assert coordinator is not None
                        return coordinator.handle(signal, goal_revision, signal.occurred_at)

                    claimed = await context.invoke_product("goals.attention.handle", handle)
                    attention_steps.append(
                        _project(
                            {
                                "fact": fact,
                                "signal": signal,
                                "claimed": claimed,
                                "snapshot": store.snapshot(),
                            }
                        )
                    )
        return TargetObservation(
            RunStatus.COMPLETED,
            Gate.NOT_RUN,
            _project(
                {
                    "commits": commits,
                    "final_snapshot": owner.snapshot().to_dict(),
                    "attention_steps": attention_steps,
                    "enqueued_triggers": enqueued,
                }
            ),
        )

    return LabTarget(
        "goal_commitment",
        contract_revision,
        frozenset({LabMode.ADJACENT if True in adjacent else LabMode.ISOLATION}),
        (),
        provenance,
        run,
    )


@dataclass(frozen=True)
class AttentionLabStep:
    signal: AttentionIngressSignal
    current_goal_revision: int
    now: datetime


@dataclass(frozen=True)
class AttentionLabCase:
    fixture: ValidationFixture
    steps: tuple[AttentionLabStep, ...]
    policy: AttentionSchedulingPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.policy, AttentionSchedulingPolicy):
            raise ValueError("注意の割当方針が不正です")
        if not self.steps or any(not isinstance(x, AttentionLabStep) for x in self.steps):
            raise ValueError("注意の入力手順が必要です")
        object.__setattr__(self, "steps", tuple(self.steps))

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "policy": self.policy,
                "steps": [
                    {
                        "signal": step.signal,
                        "current_goal_revision": step.current_goal_revision,
                        "now": step.now,
                    }
                    for step in self.steps
                ],
            }
        )


def attention_target(
    cases: tuple[AttentionLabCase, ...],
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("注意の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        store = AttentionTurnStore(case.policy)
        enqueued: list[ExecutiveTriggerEligibility] = []
        coordinator = AttentionCoordinator(store, store, enqueued.append)
        states: list[JsonValue] = []
        for step in case.steps:

            async def handle(item: AttentionLabStep = step) -> ExecutiveTriggerEligibility | None:
                return coordinator.handle(item.signal, item.current_goal_revision, item.now)

            claimed = await context.invoke_product("attention.handle", handle)
            states.append(_project({"claimed": claimed, "snapshot": store.snapshot()}))
        return TargetObservation(
            RunStatus.COMPLETED,
            Gate.NOT_RUN,
            _project(
                {
                    "steps": states,
                    "enqueued_triggers": enqueued,
                }
            ),
        )

    return LabTarget(
        "attention", contract_revision, frozenset({LabMode.ISOLATION}), (), provenance, run
    )
