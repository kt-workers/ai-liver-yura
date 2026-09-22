"""身体運動計画の製品入口を呼び、公開契約の入出力を記録する。"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from enum import Enum
from typing import cast

from app.domain.body_motion_planning import (
    BodyMotionPlanAuthority,
    BodyMotionPlanner,
    BodyMotionPlanningContextSnapshot,
    BodyMotionPlanningLiveStatePort,
    BodyMotionPlanningPolicy,
)
from app.domain.contracts.common import JsonValue, freeze_json
from app.usecases.ports.llm import LLMRolePort

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    aware,
)
from .llm_port import LabLLMPortFactory, ObservedLLMRolePort, resolve_port
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
        and type(value).__module__.startswith("app.domain.")
    ):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    raise ValueError("身体の公開契約に未対応の値があります")


def _project(value: object) -> JsonValue:
    return freeze_json(
        cast(JsonValue, json.loads(json.dumps(value, default=_encode, allow_nan=False)))
    )


@dataclass(frozen=True)
class BodyPlanningLabCase:
    fixture: ValidationFixture
    snapshot: BodyMotionPlanningContextSnapshot
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, BodyMotionPlanningContextSnapshot):
            raise ValueError("身体運動計画の製品入力が不正です")
        aware(self.created_at)

    def typed_inputs(self) -> JsonValue:
        return _project({"snapshot": self.snapshot, "created_at": self.created_at})


def body_planning_target(
    cases: tuple[BodyPlanningLabCase, ...],
    port: LLMRolePort | LabLLMPortFactory,
    live_state: BodyMotionPlanningLiveStatePort,
    policy: BodyMotionPlanningPolicy,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("身体運動計画の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        prefix = f"{context.run_id}:{fixture.scenario_id}:{context.iteration}"
        snapshot = replace(case.snapshot, request_id=prefix, trace_id=prefix)
        owner = BodyMotionPlanner(
            ObservedLLMRolePort(
                context, resolve_port(port, context), {"body_motion_planning": "body.planning.llm"}
            ),
            live_state,
            BodyMotionPlanAuthority(),
            policy,
        )
        result = await context.invoke_product(
            "body.plan",
            lambda: owner.plan(
                snapshot,
                candidate_id=f"{prefix}:candidate",
                plan_id=f"{prefix}:plan",
                created_at=case.created_at,
            ),
        )
        return TargetObservation(RunStatus.COMPLETED, Gate.NOT_RUN, _project(result))

    stages = frozenset({"body.planning.llm"})
    return LabTarget(
        "body_planning",
        contract_revision,
        frozenset({LabMode.ISOLATION}),
        provider_policy_refs,
        provenance,
        run,
        stages,
        stages,
    )
