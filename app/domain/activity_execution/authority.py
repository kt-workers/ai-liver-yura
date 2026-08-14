from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from threading import Lock

from app.domain.contracts import ExecutionResult, ExecutionStatus, RevisionVector
from app.domain.contracts.common import (
    freeze_json,
    require_aware,
    require_identifier,
    utc_instant,
)

from .contracts import (
    ActivityExecutionRecord,
    ActivityInvocation,
    CapabilityBinding,
    ExecutionAdapterReport,
    ExecutionEffectKind,
    ExecutionPreflightSnapshot,
)


class ActivityExecutionAuthority:
    """command admissionとActual Execution Factを所有する同期Authority。"""

    def __init__(
        self,
        allowed_authorities: tuple[tuple[str, str], ...] = (
            ("executive", "conscious_goal_action"),
            ("system", "runtime_control"),
        ),
    ) -> None:
        self._allowed_authorities = frozenset(allowed_authorities)
        self._records: dict[str, ActivityExecutionRecord] = {}
        self._invocation_ids: set[str] = set()
        self._lock = Lock()

    def admit(
        self, invocation: ActivityInvocation, current: ExecutionPreflightSnapshot
    ) -> ActivityExecutionRecord:
        if not isinstance(invocation, ActivityInvocation):
            raise ValueError("invocation must be ActivityInvocation")
        if not isinstance(current, ExecutionPreflightSnapshot):
            raise ValueError("current must be ExecutionPreflightSnapshot")
        command = invocation.command
        authority_key = (command.authority.owner, command.authority.scope)
        if authority_key not in self._allowed_authorities:
            raise ValueError("command authority is not allowed")
        if command.authority.reference_id != command.decision_id:
            raise ValueError("command authority reference does not match decision")
        requested = ExecutionResult(
            command.command_id,
            ExecutionStatus.REQUESTED,
            invocation.requested_at,
            command.revisions,
        )
        admitted_at = (
            current.captured_at
            if utc_instant(current.captured_at) >= utc_instant(invocation.requested_at)
            else invocation.requested_at
        )
        with self._lock:
            if command.command_id in self._records:
                raise ValueError("command is already admitted")
            if invocation.invocation_id in self._invocation_ids:
                raise ValueError("invocation is already admitted")
            bindings = self._select_bindings(command.required_capabilities, current)
            failure = self._preflight_failure(invocation, current, bindings, admitted_at)
            if bindings is None:
                result = requested.transition_to(
                    ExecutionStatus.UNSUPPORTED,
                    admitted_at,
                    details={"code": "capability_unavailable"},
                )
                bindings_tuple: tuple[CapabilityBinding, ...] = ()
            elif failure is not None:
                status, code = failure
                result = requested.transition_to(status, admitted_at, details={"code": code})
                bindings_tuple = bindings
            else:
                result = requested.transition_to(ExecutionStatus.ACCEPTED, admitted_at)
                bindings_tuple = bindings
            record = ActivityExecutionRecord(invocation, bindings_tuple, result)
            self._records[command.command_id] = record
            self._invocation_ids.add(invocation.invocation_id)
            return record

    def start(
        self,
        command_id: str,
        current: ExecutionPreflightSnapshot,
        occurred_at: datetime,
        dispatch_id: str,
    ) -> ActivityExecutionRecord:
        require_aware(occurred_at, "occurred_at")
        require_identifier(dispatch_id, "dispatch_id")
        with self._lock:
            record = self._require_record(command_id)
            if record.terminal:
                return record
            if record.result.status not in {ExecutionStatus.ACCEPTED, ExecutionStatus.PLANNED}:
                raise ValueError("execution is not awaiting start")
            failure = self._preflight_failure(
                record.invocation, current, record.bindings, occurred_at
            )
            if failure is None:
                result = record.result.transition_to(ExecutionStatus.STARTED, occurred_at)
            else:
                status, code = failure
                result = record.result.transition_to(status, occurred_at, details={"code": code})
            updated = replace(
                record,
                result=result,
                dispatch_id=dispatch_id if result.status is ExecutionStatus.STARTED else None,
            )
            self._records[command_id] = updated
            return updated

    def apply_report(self, report: ExecutionAdapterReport) -> ActivityExecutionRecord:
        if not isinstance(report, ExecutionAdapterReport):
            raise ValueError("report must be ExecutionAdapterReport")
        with self._lock:
            record = self._require_record(report.command_id)
            if report.invocation_id != record.invocation.invocation_id:
                raise ValueError("report invocation does not match record")
            if report.dispatch_id != record.dispatch_id:
                raise ValueError("report dispatch does not match record")
            binding_keys = {
                (item.capability_id, item.descriptor_revision) for item in record.bindings
            }
            for effect in report.effects:
                if effect.operation_ref != record.invocation.operation_ref:
                    raise ValueError("effect operation does not match invocation")
                if (effect.capability_id, effect.descriptor_revision) not in binding_keys:
                    raise ValueError("effect capability does not match binding")
            effect_refs = tuple(
                dict.fromkeys(
                    (
                        *record.result.effect_refs,
                        *(item.effect_id for item in report.effects),
                    )
                )
            )
            deadline = record.invocation.command.deadline_at
            if deadline is not None and utc_instant(report.occurred_at) >= utc_instant(deadline):
                result = record.result
                if report.effects and result.status is ExecutionStatus.STARTED:
                    milestone = (
                        ExecutionStatus.APPLIED
                        if any(item.kind is ExecutionEffectKind.APPLIED for item in report.effects)
                        else ExecutionStatus.OBSERVABLE
                    )
                    result = result.transition_to(
                        milestone,
                        report.occurred_at,
                        details=report.details,
                        effect_refs=effect_refs,
                    )
                result = result.transition_to(
                    ExecutionStatus.TIMED_OUT,
                    report.occurred_at,
                    details={"code": "deadline_elapsed"},
                    effect_refs=effect_refs,
                )
                updated = replace(record, result=result)
                self._records[report.command_id] = updated
                return updated
            updated = replace(
                record,
                result=record.result.transition_to(
                    report.status,
                    report.occurred_at,
                    details=report.details,
                    effect_refs=effect_refs,
                ),
            )
            self._records[report.command_id] = updated
            return updated

    def fail_adapter_contract(
        self, command_id: str, occurred_at: datetime
    ) -> ActivityExecutionRecord:
        require_aware(occurred_at, "occurred_at")
        with self._lock:
            record = self._require_record(command_id)
            if record.terminal:
                return record
            failure_at = (
                occurred_at
                if utc_instant(occurred_at) >= utc_instant(record.result.occurred_at)
                else record.result.occurred_at
            )
            updated = replace(
                record,
                result=record.result.transition_to(
                    ExecutionStatus.FAILED,
                    failure_at,
                    details={"code": "adapter_contract_failure"},
                ),
            )
            self._records[command_id] = updated
            return updated

    def request_cancellation(
        self, command_id: str, reason: str, requested_at: datetime
    ) -> ActivityExecutionRecord:
        require_aware(requested_at, "requested_at")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
        with self._lock:
            record = self._require_record(command_id)
            if record.terminal:
                return record
            if record.cancellation_requested_at is not None:
                return record
            if utc_instant(requested_at) < utc_instant(record.result.occurred_at):
                raise ValueError("cancellation timestamp cannot predate current execution state")
            result = record.result
            if result.status in {
                ExecutionStatus.REQUESTED,
                ExecutionStatus.ACCEPTED,
                ExecutionStatus.PLANNED,
            }:
                result = result.transition_to(
                    ExecutionStatus.CANCELLED,
                    requested_at,
                    details={"code": "cancelled_before_start"},
                )
            updated = replace(
                record,
                result=result,
                cancellation_reason=reason,
                cancellation_requested_at=requested_at,
            )
            self._records[command_id] = updated
            return updated

    def supersede(self, command_id: str, occurred_at: datetime) -> ActivityExecutionRecord:
        with self._lock:
            record = self._require_record(command_id)
            updated = replace(
                record,
                result=record.result.transition_to(
                    ExecutionStatus.SUPERSEDED,
                    occurred_at,
                    details={"code": "stale_after_start"},
                ),
            )
            self._records[command_id] = updated
            return updated

    def snapshot(self, command_id: str) -> ActivityExecutionRecord | None:
        with self._lock:
            return self._records.get(command_id)

    def _require_record(self, command_id: str) -> ActivityExecutionRecord:
        record = self._records.get(command_id)
        if record is None:
            raise ValueError("execution record does not exist")
        return record

    @staticmethod
    def _select_bindings(
        requirements: tuple[object, ...], current: ExecutionPreflightSnapshot
    ) -> tuple[CapabilityBinding, ...] | None:
        from app.domain.contracts import CapabilityRequirement

        bindings: list[CapabilityBinding] = []
        for requirement in requirements:
            assert isinstance(requirement, CapabilityRequirement)
            candidates = sorted(
                (item for item in current.capabilities if item.satisfies(requirement)),
                key=lambda item: item.capability_id,
            )
            if not candidates:
                return None
            selected = candidates[0]
            bindings.append(
                CapabilityBinding(requirement, selected.capability_id, selected.revision)
            )
        return tuple(bindings)

    @staticmethod
    def _preflight_failure(
        invocation: ActivityInvocation,
        current: ExecutionPreflightSnapshot,
        bindings: tuple[CapabilityBinding, ...] | None,
        occurred_at: datetime,
    ) -> tuple[ExecutionStatus, str] | None:
        command = invocation.command
        if utc_instant(current.captured_at) < utc_instant(command.issued_at):
            return ExecutionStatus.SUPERSEDED, "preflight_predates_command"
        if command.deadline_at is not None and utc_instant(occurred_at) >= utc_instant(
            command.deadline_at
        ):
            return ExecutionStatus.TIMED_OUT, "deadline_elapsed"
        if not _revisions_match(command.revisions, current.revisions):
            return ExecutionStatus.SUPERSEDED, "stale_revision"
        if bindings is not None:
            capabilities = {item.capability_id: item for item in current.capabilities}
            for binding in bindings:
                descriptor = capabilities.get(binding.capability_id)
                if (
                    descriptor is None
                    or descriptor.revision != binding.descriptor_revision
                    or not descriptor.satisfies(binding.requirement)
                ):
                    return ExecutionStatus.SUPERSEDED, "capability_changed"
        preconditions = {item.precondition_id: item for item in current.preconditions}
        for expected in command.preconditions:
            actual = preconditions.get(expected.precondition_id)
            if (
                actual is None
                or actual.subject_ref != expected.subject_ref
                or actual.predicate != expected.predicate
                or freeze_json(actual.actual) != freeze_json(expected.expected)
            ):
                return ExecutionStatus.REJECTED, "precondition_failed"
        return None


def _revisions_match(expected: RevisionVector, current: RevisionVector) -> bool:
    if expected.source_context_revision != current.source_context_revision:
        return False
    if expected.goal_revision is not None and expected.goal_revision != current.goal_revision:
        return False
    return (
        expected.attention_revision is None
        or expected.attention_revision == current.attention_revision
    )
