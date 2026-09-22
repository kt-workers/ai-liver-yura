"""複数の本番接続を同時実行し、各接続の範囲と証拠を保持する。"""

import asyncio
import json
from dataclasses import dataclass, fields, is_dataclass, replace
from typing import cast

from app.domain.contracts.common import JsonValue, freeze_json

from .body import _encode as encode_domain
from .contracts import (
    Gate,
    LabMode,
    LabRunSpec,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    ValidationRunResult,
)
from .runtime import LabTarget, RunContext, ValidationRunner


def _encode(value: object) -> object:
    if (
        is_dataclass(value)
        and not isinstance(value, type)
        and type(value).__module__ == "app.subsystems.validation.contracts"
    ):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    return encode_domain(value)


def _project(value: object) -> JsonValue:
    return freeze_json(
        cast(JsonValue, json.loads(json.dumps(value, default=_encode, allow_nan=False)))
    )


@dataclass(frozen=True)
class ParallelInput:
    spec: LabRunSpec
    fixture: ValidationFixture


@dataclass(frozen=True)
class ParallelCase:
    fixture: ValidationFixture
    inputs: tuple[ParallelInput, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", tuple(self.inputs))
        if len(self.inputs) < 2 or len({x.spec.run_id for x in self.inputs}) != len(self.inputs):
            raise ValueError("並行検証には一意の実行識別子を持つ二つ以上の入力が必要です")

    def typed_inputs(self) -> JsonValue:
        return _project([{"spec": x.spec, "fixture": x.fixture} for x in self.inputs])


def parallel_target(
    cases: tuple[ParallelCase, ...],
    targets: tuple[LabTarget, ...],
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("並行検証の条件は重複できません")
    if any(
        target.module == "parallel" or target.provenance.git_head != provenance.git_head
        for target in targets
    ):
        raise ValueError("並行検証の再帰接続や製品の異なるリビジョンの混在はできません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or fixture != case.fixture or fixture.typed_inputs != case.typed_inputs():
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        count = len(case.inputs)
        if count > min(context.policy.max_tasks, context.policy.max_intervals):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        child_policy = replace(
            context.policy,
            max_tasks=context.policy.max_tasks // count,
            max_intervals=context.policy.max_intervals // count,
        )
        children = []
        for index, item in enumerate(case.inputs):
            runner = ValidationRunner(targets, child_policy)
            context.add_cleanup(f"parallel.child:{index}", runner.close)
            child_spec = replace(
                item.spec, run_id=f"{context.run_id}:{context.iteration}:{index}:{item.spec.run_id}"
            )

            async def invoke(
                runner: ValidationRunner = runner,
                child_spec: LabRunSpec = child_spec,
                item: ParallelInput = item,
            ) -> object:
                return await runner.run(child_spec, item.fixture)

            children.append(context.spawn(f"parallel.child:{index}", invoke))
        results = await asyncio.gather(*children)
        completed = [cast(ValidationRunResult, result) for result in results]
        status = next(
            (x.status for x in completed if x.status is not RunStatus.COMPLETED),
            RunStatus.COMPLETED,
        )
        return TargetObservation(
            status,
            Gate.NOT_RUN,
            _project(
                {
                    "child_policy": child_policy,
                    "results": [result.to_dict() for result in completed],
                }
            ),
        )

    return LabTarget(
        "parallel", contract_revision, frozenset({LabMode.SYSTEM_SLICE}), (), provenance, run
    )
