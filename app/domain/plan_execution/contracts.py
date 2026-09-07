"""計画全体の承認対象を固定し、手順の引数と権限の拡張を拒否する。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import InitVar, dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts import PreconditionRef
from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    require_revision,
    thaw_json,
    timestamp_to_json,
    utc_instant,
)

if TYPE_CHECKING:
    from app.domain.goal_planning.contracts import ActivityPlan

_AUTHORIZATION_PROOF = object()


@dataclass(frozen=True, slots=True)
class PlanExecutionPolicy:
    policy_id: str
    revision: int
    max_active_plans: int
    max_inflight_steps: int
    max_retained_records: int
    max_arguments_bytes: int

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.revision, "revision")
        for name in (
            "max_active_plans",
            "max_inflight_steps",
            "max_retained_records",
            "max_arguments_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name}には正の整数を指定してください")


@dataclass(frozen=True, slots=True)
class PlanStepExecutionBinding:
    step_id: str
    operation_ref: str
    target_ref: str | None
    arguments: JsonValue
    argument_fact_refs: tuple[str, ...]
    preconditions: tuple[PreconditionRef, ...]

    def __post_init__(self) -> None:
        require_identifier(self.step_id, "step_id")
        require_identifier(self.operation_ref, "operation_ref")
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        arguments = freeze_json(self.arguments)
        if not isinstance(arguments, Mapping):
            raise ValueError("操作引数はオブジェクトでなければなりません")
        refs = tuple(self.argument_fact_refs)
        for ref in refs:
            require_identifier(ref, "argument_fact_ref")
        if len(refs) != len(set(refs)) or (arguments and not refs):
            raise ValueError("操作引数には重複のない由来参照が必要です")
        preconditions = tuple(self.preconditions)
        if any(not isinstance(item, PreconditionRef) for item in preconditions):
            raise ValueError("事前条件にはPreconditionRefを指定してください")
        ids = [item.precondition_id for item in preconditions]
        if len(ids) != len(set(ids)):
            raise ValueError("事前条件の識別子は重複できません")
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "argument_fact_refs", refs)
        object.__setattr__(self, "preconditions", preconditions)

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "operation_ref": self.operation_ref,
            "target_ref": self.target_ref,
            "arguments": thaw_json(self.arguments),
            "argument_fact_refs": list(self.argument_fact_refs),
            "preconditions": [item.to_dict() for item in self.preconditions],
        }


@dataclass(frozen=True, slots=True)
class PlanExecutionScope:
    scope_id: str
    plan: ActivityPlan
    bindings: tuple[PlanStepExecutionBinding, ...]
    captured_at: datetime
    deadline_at: datetime
    policy: PlanExecutionPolicy
    bounds_policy: BrainOperationalBoundsPolicy

    def __post_init__(self) -> None:
        from app.domain.goal_planning.bounds import validate_plan_bounds
        from app.domain.goal_planning.contracts import ActivityPlan, GoalPlanningOutcome

        require_identifier(self.scope_id, "scope_id")
        if not isinstance(self.plan, ActivityPlan):
            raise ValueError("承認対象には所有者が確定した計画が必要です")
        if not isinstance(self.policy, PlanExecutionPolicy):
            raise ValueError("計画実行の容量方針が必要です")
        if not isinstance(self.bounds_policy, BrainOperationalBoundsPolicy):
            raise ValueError("計画と判断の容量方針が必要です")
        candidate = self.plan.candidate
        if candidate.outcome is not GoalPlanningOutcome.PLANNED:
            raise ValueError("実行手順のある確定計画だけを承認対象にできます")
        validate_plan_bounds(candidate, self.bounds_policy)
        require_aware(self.captured_at, "captured_at")
        require_aware(self.deadline_at, "deadline_at")
        if utc_instant(self.captured_at) < utc_instant(self.plan.committed_at):
            raise ValueError("承認対象は計画確定より前に作成できません")
        if utc_instant(self.deadline_at) <= utc_instant(self.captured_at):
            raise ValueError("承認対象の期限は取得時刻より後でなければなりません")
        bindings = tuple(self.bindings)
        if any(not isinstance(item, PlanStepExecutionBinding) for item in bindings):
            raise ValueError("手順の束縛にはPlanStepExecutionBindingを指定してください")
        ids = [item.step_id for item in bindings]
        steps = {step.step_id: step for step in candidate.steps}
        if len(ids) != len(set(ids)) or set(ids) != set(steps):
            raise ValueError("確定計画の全手順に重複のない束縛が必要です")
        conditions: dict[str, PreconditionRef] = {}
        for binding in bindings:
            for condition in binding.preconditions:
                previous = conditions.setdefault(condition.precondition_id, condition)
                if previous != condition:
                    raise ValueError("同一の事前条件参照に異なる内容を束縛できません")
            step = steps[binding.step_id]
            if binding.operation_ref != step.operation_ref or binding.target_ref != step.target_ref:
                raise ValueError("手順の操作または対象を変更できません")
            if {item.precondition_id for item in binding.preconditions} != set(
                step.precondition_ids
            ):
                raise ValueError("手順の事前条件を省略・追加できません")
            if len(binding.argument_fact_refs) > self.bounds_policy.executive.max_refs_per_intent:
                raise ValueError("操作引数の由来参照が上限を超えています")
            size = len(json.dumps(thaw_json(binding.arguments), ensure_ascii=False).encode("utf-8"))
            if size > self.policy.max_arguments_bytes:
                raise ValueError("操作引数の容量が上限を超えています")
        object.__setattr__(self, "bindings", bindings)
        payload_bytes = len(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        if payload_bytes > self.bounds_policy.executive.max_fact_payload_json_bytes:
            raise ValueError("計画承認対象全体の容量が判断事実の上限を超えています")

    def to_dict(self) -> dict[str, object]:
        return {
            "scope_id": self.scope_id,
            "plan": self.plan.to_dict(),
            "bindings": [item.to_dict() for item in self.bindings],
            "captured_at": timestamp_to_json(self.captured_at),
            "deadline_at": timestamp_to_json(self.deadline_at),
            "policy_id": self.policy.policy_id,
            "policy_revision": self.policy.revision,
            "max_active_plans": self.policy.max_active_plans,
            "max_inflight_steps": self.policy.max_inflight_steps,
            "max_retained_records": self.policy.max_retained_records,
            "max_arguments_bytes": self.policy.max_arguments_bytes,
            "bounds_policy_id": self.bounds_policy.policy_id,
            "bounds_policy_revision": self.bounds_policy.policy_revision,
        }


@dataclass(frozen=True, slots=True)
class PlanExecutionAuthorization:
    authorization_id: str
    decision_id: str
    intent_id: str
    scope: PlanExecutionScope
    committed_at: datetime
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        if _proof is not _AUTHORIZATION_PROOF:
            raise ValueError("計画実行承認は実行判断の確定所有者だけが発行できます")
        for name in ("authorization_id", "decision_id", "intent_id"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.scope, PlanExecutionScope):
            raise ValueError("計画実行承認には固定された承認対象が必要です")
        require_aware(self.committed_at, "committed_at")
        if not (
            utc_instant(self.scope.captured_at)
            <= utc_instant(self.committed_at)
            < utc_instant(self.scope.deadline_at)
        ):
            raise ValueError("承認の確定時刻が有効な期間の外にあります")

    def to_dict(self) -> dict[str, object]:
        return {
            "authorization_id": self.authorization_id,
            "decision_id": self.decision_id,
            "intent_id": self.intent_id,
            "scope": self.scope.to_dict(),
            "committed_at": timestamp_to_json(self.committed_at),
        }
