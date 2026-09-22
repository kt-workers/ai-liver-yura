"""出来事の定型評価から本番の状態更新への隣接接続を検証する。"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.appraisal import (
    AppraisalCandidate,
    DeterministicAppraisalRule,
    InternalStateReducer,
    InternalStateSnapshot,
    appraise_event,
)
from app.domain.contracts import EventEnvelope
from app.domain.contracts.common import JsonValue, require_revision

from .body import _project
from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    aware,
)
from .runtime import LabTarget, RunContext


@dataclass(frozen=True)
class EventAppraisalSettings:
    state: InternalStateSnapshot
    rules: tuple[DeterministicAppraisalRule, ...]
    current_source_context_revision: int
    created_at: datetime
    committed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.state, InternalStateSnapshot):
            raise ValueError("評価の初期状態が不正です")
        rules = tuple(self.rules)
        if any(not isinstance(rule, DeterministicAppraisalRule) for rule in rules):
            raise ValueError("定型評価の規則が不正です")
        object.__setattr__(self, "rules", rules)
        require_revision(self.current_source_context_revision, "source_context_revision")
        aware(self.created_at)
        aware(self.committed_at)

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "state": self.state,
                "rules": self.rules,
                "current_source_context_revision": self.current_source_context_revision,
                "created_at": self.created_at,
                "committed_at": self.committed_at,
            }
        )


async def appraise_and_commit_event(
    context: RunContext,
    event: EventEnvelope,
    settings: EventAppraisalSettings,
    *,
    candidate_id: str,
) -> JsonValue:
    reducer = InternalStateReducer(settings.state)
    before = reducer.snapshot()

    async def appraise() -> AppraisalCandidate | None:
        return appraise_event(
            event,
            before,
            settings.rules,
            candidate_id=candidate_id,
            created_at=settings.created_at,
        )

    candidate = await context.invoke_product("appraisal.fast", appraise)
    after = before
    if candidate is not None:

        async def commit() -> InternalStateSnapshot:
            return reducer.commit(
                candidate,
                current_source_context_revision=settings.current_source_context_revision,
                committed_at=settings.committed_at,
            )

        after = await context.invoke_product("appraisal.state_commit", commit)
    return _project({"before": before, "candidate": candidate, "after": after})


@dataclass(frozen=True)
class FastAppraisalCase:
    fixture: ValidationFixture
    event: EventEnvelope
    state: InternalStateSnapshot
    rules: tuple[DeterministicAppraisalRule, ...]
    current_source_context_revision: int
    created_at: datetime
    committed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "rules", tuple(self.rules))

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "event": self.event,
                "state": self.state,
                "rules": self.rules,
                "current_source_context_revision": self.current_source_context_revision,
                "created_at": self.created_at,
                "committed_at": self.committed_at,
            }
        )


def fast_appraisal_target(
    cases: tuple[FastAppraisalCase, ...],
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("速い状況評価の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or fixture != case.fixture or fixture.typed_inputs != case.typed_inputs():
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        output = await appraise_and_commit_event(
            context,
            case.event,
            EventAppraisalSettings(
                case.state,
                case.rules,
                case.current_source_context_revision,
                case.created_at,
                case.committed_at,
            ),
            candidate_id=f"{context.run_id}:{fixture.scenario_id}:{context.iteration}",
        )
        return TargetObservation(RunStatus.COMPLETED, Gate.NOT_RUN, output)

    return LabTarget(
        "fast_appraisal", contract_revision, frozenset({LabMode.ADJACENT}), (), provenance, run
    )
