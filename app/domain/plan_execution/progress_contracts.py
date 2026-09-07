"""計画の実行事実と、既存判断所有者による完了評価を区別する。"""

from __future__ import annotations

import json
from dataclasses import InitVar, dataclass
from datetime import datetime

from app.domain.activity_execution.contracts import ActivityExecutionRecord
from app.domain.contracts import AuthorityRef, ExecutionStatus, IntentKind, IntentRef
from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    timestamp_to_json,
    utc_instant,
)

from .contracts import PlanExecutionAuthorization

_ASSESSMENT_PROOF = object()


def _ids(values: tuple[str, ...], name: str, *, non_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{name}は参照の配列でなければなりません")
    result = tuple(values)
    for value in result:
        require_identifier(value, name)
    if (non_empty and not result) or len(result) != len(set(result)):
        raise ValueError(f"{name}の参照件数または重複が不正です")
    return result


@dataclass(frozen=True, slots=True)
class PlanExecutionObservation:
    step_id: str
    attempt: int
    record: ActivityExecutionRecord

    def __post_init__(self) -> None:
        require_identifier(self.step_id, "step_id")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("試行回数は1以上の整数でなければなりません")
        if not isinstance(self.record, ActivityExecutionRecord):
            raise ValueError("活動の確定記録が必要です")

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "attempt": self.attempt,
            "invocation": self.record.invocation.to_dict(),
            "result": self.record.result.to_dict(),
            "record_revision": self.record.record_revision,
            "effect_uncertainty": self.record.effect_uncertainty.value,
        }


@dataclass(frozen=True, slots=True)
class PlanProgressContext:
    context_id: str
    authorization: PlanExecutionAuthorization
    observations: tuple[PlanExecutionObservation, ...]

    def __post_init__(self) -> None:
        require_identifier(self.context_id, "context_id")
        if not isinstance(self.authorization, PlanExecutionAuthorization):
            raise ValueError("計画実行の承認が必要です")
        if not isinstance(self.observations, (tuple, list)):
            raise ValueError("実行観測は配列でなければなりません")
        values = tuple(self.observations)
        if any(not isinstance(item, PlanExecutionObservation) for item in values):
            raise ValueError("計画進行の観測には型付きの実行記録が必要です")
        scope = self.authorization.scope
        steps = {item.step_id: item for item in scope.plan.candidate.steps}
        bindings = {item.step_id: item for item in scope.bindings}
        if len({item.step_id for item in values}) != len(values):
            raise ValueError("各手順の最新観測は1件だけ保持できます")
        if len({item.record.result.command_id for item in values}) != len(values):
            raise ValueError("同じ実行命令を複数手順の観測にできません")
        if len(values) > scope.policy.max_retained_records:
            raise ValueError("計画の実行観測が保持上限を超えています")
        for item in values:
            if item.step_id not in steps:
                raise ValueError("計画外の手順を観測へ混入できません")
            step = steps[item.step_id]
            binding = bindings[item.step_id]
            invocation = item.record.invocation
            resumed = binding.resumed_invocation
            if resumed is not None and (item.attempt != 1 or invocation != resumed):
                raise ValueError("再開した既存要求と観測が一致しません")
            if resumed is None and (
                item.attempt > step.retry_limit + 1
                or invocation.command.decision_id != self.authorization.decision_id
                or invocation.command.intent_ref
                != IntentRef(IntentKind.ACTIVITY, self.authorization.intent_id)
                or invocation.command.authority
                != AuthorityRef(
                    "executive", "conscious_goal_action", self.authorization.decision_id
                )
                or utc_instant(invocation.command.issued_at)
                < utc_instant(self.authorization.committed_at)
                or utc_instant(invocation.command.issued_at) >= utc_instant(scope.deadline_at)
                or (
                    invocation.command.deadline_at is not None
                    and utc_instant(invocation.command.deadline_at) > utc_instant(scope.deadline_at)
                )
            ):
                raise ValueError("新規実行の権限または期限が承認済みの手順と一致しません")
            if (
                invocation.operation_ref != binding.operation_ref
                or invocation.target_ref != binding.target_ref
                or invocation.arguments != binding.arguments
                or invocation.command.required_capabilities != step.required_capabilities
                or invocation.command.preconditions != binding.preconditions
            ):
                raise ValueError("活動の実行記録が承認済みの手順と一致しません")
        object.__setattr__(self, "observations", values)
        size = len(json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":")).encode())
        if size > scope.bounds_policy.executive.max_fact_payload_json_bytes:
            raise ValueError("計画進行の観測が判断事実の容量上限を超えています")

    def to_dict(self) -> dict[str, object]:
        return {
            "context_id": self.context_id,
            "authorization": self.authorization.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
        }


@dataclass(frozen=True, slots=True)
class PlanStepCompletionClaim:
    step_id: str
    condition_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identifier(self.step_id, "step_id")
        object.__setattr__(
            self, "condition_refs", _ids(self.condition_refs, "condition_refs", non_empty=False)
        )
        object.__setattr__(self, "evidence_refs", _ids(self.evidence_refs, "evidence_refs"))

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "condition_refs": list(self.condition_refs),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class PlanProgressAssessment:
    decision_id: str
    intent_id: str
    context: PlanProgressContext
    claims: tuple[PlanStepCompletionClaim, ...]
    committed_at: datetime
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        if _proof is not _ASSESSMENT_PROOF:
            raise ValueError("計画の完了評価は実行判断の確定所有者だけが発行できます")
        for name in ("decision_id", "intent_id"):
            require_identifier(getattr(self, name), name)
        require_aware(self.committed_at, "committed_at")
        if not isinstance(self.context, PlanProgressContext):
            raise ValueError("計画進行の評価対象が必要です")
        if not isinstance(self.claims, (tuple, list)):
            raise ValueError("完了条件の評価は配列でなければなりません")
        claims = tuple(self.claims)
        if not claims or any(not isinstance(item, PlanStepCompletionClaim) for item in claims):
            raise ValueError("手順の完了条件評価が1件以上必要です")
        if len({item.step_id for item in claims}) != len(claims):
            raise ValueError("同じ手順の完了を重複評価できません")
        steps = {
            item.step_id: item for item in self.context.authorization.scope.plan.candidate.steps
        }
        refs = {self.context.context_id}
        for claim in claims:
            refs.update((claim.step_id,) + claim.condition_refs + claim.evidence_refs)
        if len(refs) > self.context.authorization.scope.bounds_policy.executive.max_refs_per_intent:
            raise ValueError("完了条件の評価参照が判断意図の上限を超えています")
        records = {item.step_id: item.record for item in self.context.observations}
        for claim in claims:
            record = records.get(claim.step_id)
            if record is None or record.result.status is not ExecutionStatus.COMPLETED:
                raise ValueError("実行が正常終了していない手順を完了評価できません")
            if set(claim.condition_refs) != set(steps[claim.step_id].completion_condition_refs):
                raise ValueError("手順の完了条件を省略・追加できません")
            if utc_instant(self.committed_at) < utc_instant(record.result.occurred_at):
                raise ValueError("実行結果より前に手順を完了評価できません")
        object.__setattr__(self, "claims", claims)

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "intent_id": self.intent_id,
            "context_id": self.context.context_id,
            "claims": [item.to_dict() for item in self.claims],
            "committed_at": timestamp_to_json(self.committed_at),
        }
