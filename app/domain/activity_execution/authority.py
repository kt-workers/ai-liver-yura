from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from app.domain.contracts import (
    ExecutionResult,
    ExecutionStatus,
    RevisionVector,
    SourceLifecycleOperation,
)
from app.domain.contracts.common import (
    freeze_json,
    require_aware,
    require_identifier,
    utc_instant,
)
from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    AuthorityReadPublication,
    authority_mutation,
)

from .contracts import (
    ActivityExecutionCommitResult,
    ActivityExecutionLifecycleFact,
    ActivityExecutionRecord,
    ActivityInvocation,
    CapabilityBinding,
    ExecutionAdapterReport,
    ExecutionEffectKind,
    ExecutionPreflightSnapshot,
)
from .observation import (
    ExecutionObservationIngressPolicy,
    ExecutionObservationSourceBinding,
    ObservedExecutionFactRecord,
    TrustedExecutionObservation,
    accept_observation,
    same_observation,
)


class ActivityExecutionAuthority:
    """command admissionとActual Execution Factを所有する同期Authority。"""

    def __init__(
        self,
        allowed_authorities: tuple[tuple[str, str], ...] = (
            ("executive", "conscious_goal_action"),
            ("system", "runtime_control"),
        ),
        *,
        observation_policy: ExecutionObservationIngressPolicy | None = None,
    ) -> None:
        if observation_policy is not None and not isinstance(
            observation_policy, ExecutionObservationIngressPolicy
        ):
            raise ValueError("観測受理policyが不正です")
        self._observation_policy = observation_policy
        self._observed_records: dict[tuple[str, str], ObservedExecutionFactRecord] = {}
        self._observations: dict[
            tuple[ExecutionObservationSourceBinding, str], TrustedExecutionObservation
        ] = {}
        self._allowed_authorities = frozenset(allowed_authorities)
        self._records: dict[str, ActivityExecutionRecord] = {}
        self._invocation_ids: set[str] = set()
        self._participant = AuthorityFinalizationParticipant(self, "ActivityExecutionAuthority", 50)
        self._lock = self._participant

    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant:
        """元所有者の読取と更新に共通する同期境界を公開する。"""
        return self._participant

    @authority_mutation
    def admit(
        self, invocation: ActivityInvocation, current: ExecutionPreflightSnapshot
    ) -> ActivityExecutionCommitResult:
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
            primary = invocation.primary_binding
            primary_failure = None
            if primary is not None:
                descriptor = next(
                    (c for c in current.capabilities if c.capability_id == primary.capability_id),
                    None,
                )
                if descriptor is None:
                    primary_failure = (ExecutionStatus.UNSUPPORTED, "capability_unavailable")
                elif descriptor.revision != primary.descriptor_revision:
                    primary_failure = (ExecutionStatus.SUPERSEDED, "capability_changed")
                elif not descriptor.satisfies(primary.requirement):
                    primary_failure = (ExecutionStatus.UNSUPPORTED, "capability_unavailable")
            bindings = self._select_bindings(command.required_capabilities, current, primary)
            failure = self._preflight_failure(invocation, current, bindings, admitted_at)
            if primary_failure is not None:
                status, code = primary_failure
                result = requested.transition_to(status, admitted_at, details={"code": code})
                bindings_tuple: tuple[CapabilityBinding, ...] = (primary,) if primary else ()
            elif bindings is None:
                result = requested.transition_to(
                    ExecutionStatus.UNSUPPORTED,
                    admitted_at,
                    details={"code": "capability_unavailable"},
                )
                bindings_tuple = (primary,) if primary else ()
            elif failure is not None:
                status, code = failure
                result = requested.transition_to(status, admitted_at, details={"code": code})
                bindings_tuple = bindings
            else:
                result = requested.transition_to(ExecutionStatus.ACCEPTED, admitted_at)
                bindings_tuple = bindings
            requested_record = ActivityExecutionRecord(invocation, bindings_tuple, requested)
            requested_fact = self._commit(None, requested_record)
            record = replace(requested_record, result=result, record_revision=1)
            lifecycle_facts = (requested_fact, self._commit(requested_record, record))
            self._invocation_ids.add(invocation.invocation_id)
            return ActivityExecutionCommitResult(record, lifecycle_facts)

    @authority_mutation
    def start(
        self,
        command_id: str,
        current: ExecutionPreflightSnapshot,
        occurred_at: datetime,
        dispatch_id: str,
    ) -> ActivityExecutionCommitResult:
        require_aware(occurred_at, "occurred_at")
        require_identifier(dispatch_id, "dispatch_id")
        with self._lock:
            record = self._require_record(command_id)
            if record.terminal:
                return ActivityExecutionCommitResult(record, ())
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
            updated = replace(updated, record_revision=record.record_revision + 1)
            return ActivityExecutionCommitResult(updated, (self._commit(record, updated),))

    @authority_mutation
    def apply_report(self, report: ExecutionAdapterReport) -> ActivityExecutionCommitResult:
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
            new_effect_refs = tuple(
                item.effect_id
                for item in report.effects
                if item.effect_id not in record.result.effect_refs
            )
            deadline = record.invocation.command.deadline_at
            if deadline is not None and utc_instant(report.occurred_at) >= utc_instant(deadline):
                result = record.result
                if new_effect_refs:
                    has_applied = any(
                        item.kind is ExecutionEffectKind.APPLIED for item in report.effects
                    )
                    if result.status is ExecutionStatus.STARTED:
                        milestone = (
                            ExecutionStatus.APPLIED if has_applied else ExecutionStatus.OBSERVABLE
                        )
                    elif result.status is ExecutionStatus.OBSERVABLE:
                        milestone = ExecutionStatus.OBSERVABLE
                    elif result.status is ExecutionStatus.APPLIED:
                        milestone = ExecutionStatus.APPLIED
                    else:
                        raise ValueError("late effect cannot be recorded from current status")
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
                updated = replace(
                    record,
                    result=result,
                    effect_uncertainty=report.effect_uncertainty,
                )
                updated = replace(updated, record_revision=record.record_revision + 1)
                return ActivityExecutionCommitResult(updated, (self._commit(record, updated),))
            updated = replace(
                record,
                result=record.result.transition_to(
                    report.status,
                    report.occurred_at,
                    details=report.details,
                    effect_refs=effect_refs,
                ),
                effect_uncertainty=report.effect_uncertainty,
            )
            updated = replace(updated, record_revision=record.record_revision + 1)
            return ActivityExecutionCommitResult(updated, (self._commit(record, updated),))

    @authority_mutation
    def fail_adapter_contract(
        self, command_id: str, occurred_at: datetime
    ) -> ActivityExecutionCommitResult:
        require_aware(occurred_at, "occurred_at")
        with self._lock:
            record = self._require_record(command_id)
            if record.terminal:
                return ActivityExecutionCommitResult(record, ())
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
            updated = replace(updated, record_revision=record.record_revision + 1)
            return ActivityExecutionCommitResult(updated, (self._commit(record, updated),))

    @authority_mutation
    def request_cancellation(
        self, command_id: str, reason: str, requested_at: datetime
    ) -> ActivityExecutionCommitResult:
        require_aware(requested_at, "requested_at")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
        with self._lock:
            record = self._require_record(command_id)
            if record.terminal:
                return ActivityExecutionCommitResult(record, ())
            if record.cancellation_requested_at is not None:
                return ActivityExecutionCommitResult(record, ())
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
            updated = replace(updated, record_revision=record.record_revision + 1)
            return ActivityExecutionCommitResult(updated, (self._commit(record, updated),))

    @authority_mutation
    def supersede(self, command_id: str, occurred_at: datetime) -> ActivityExecutionCommitResult:
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
            updated = replace(updated, record_revision=record.record_revision + 1)
            return ActivityExecutionCommitResult(updated, (self._commit(record, updated),))

    def snapshot(self, command_id: str) -> ActivityExecutionRecord | None:
        with self._lock:
            return self._records.get(command_id)

    @authority_mutation
    def ingest_observation(
        self,
        observation: TrustedExecutionObservation,
        *,
        policy_id: str,
        policy_revision: int,
    ) -> ObservedExecutionFactRecord:
        """登録済みsourceの観測だけを、既存の所有者同期境界で受理する。"""
        policy = self._observation_policy
        if (
            policy is None
            or policy.policy_id != policy_id
            or type(policy_revision) is not int
            or policy.policy_revision != policy_revision
        ):
            raise ValueError("観測受理policyの世代が一致しません")
        if not isinstance(observation, TrustedExecutionObservation):
            raise ValueError("型付き実行観測が必要です")
        rule = next((r for r in policy.source_rules if r.source == observation.source), None)
        if rule is None or observation.status not in rule.allowed_statuses:
            raise ValueError("未登録sourceまたは許可されないstatusです")
        if any(
            e.effect_type not in rule.allowed_effect_types
            or e.kind not in rule.allowed_effect_kinds
            for e in observation.effects
        ):
            raise ValueError("source ruleに許可されないeffectです")
        key = (observation.source.source_contract_id, observation.execution_id)
        identity = (observation.source, observation.observation_id)
        previous = self._observations.get(identity)
        if previous is not None:
            if not same_observation(previous, observation):
                raise ValueError("同一observation identityの内容が矛盾しています")
            return self._observed_records[key]
        before = self._observed_records.get(key)
        if (
            rule.terminal_requires_prior_effect
            and observation.status
            in {
                ExecutionStatus.COMPLETED,
                ExecutionStatus.FAILED,
                ExecutionStatus.CANCELLED,
                ExecutionStatus.TIMED_OUT,
            }
            and (before is None or not before.result.effect_refs)
        ):
            raise ValueError("このsourceの終端には先行する確認済みeffectが必要です")
        record = accept_observation(observation, before)
        self._observed_records[key] = record
        self._observations[identity] = observation
        return record

    def observed_snapshot(
        self, source_contract_id: str, execution_id: str
    ) -> AuthorityReadPublication[ObservedExecutionFactRecord | None]:
        """観測Factと同じ所有者の世代をまとめて公開する。"""
        with self._participant:
            return AuthorityReadPublication(
                self._observed_records.get((source_contract_id, execution_id)),
                (self._participant.token(),),
            )

    def _commit(
        self, before: ActivityExecutionRecord | None, after: ActivityExecutionRecord
    ) -> ActivityExecutionLifecycleFact:
        self._records[after.result.command_id] = after
        operation = (
            SourceLifecycleOperation.OPEN
            if before is None
            else (
                SourceLifecycleOperation.CLOSE
                if after.terminal
                else SourceLifecycleOperation.REFRESH
            )
        )
        return ActivityExecutionLifecycleFact(
            f"activity-lifecycle-{after.result.command_id}-{after.record_revision}",
            after.result.command_id,
            operation,
            after.record_revision,
            None if before is None else before.record_revision,
            after.result.status,
            after.result.occurred_at,
            after.result.effect_refs,
            after.effect_uncertainty,
        )

    def _require_record(self, command_id: str) -> ActivityExecutionRecord:
        record = self._records.get(command_id)
        if record is None:
            raise ValueError("execution record does not exist")
        return record

    @staticmethod
    def _select_bindings(
        requirements: tuple[object, ...],
        current: ExecutionPreflightSnapshot,
        primary: CapabilityBinding | None = None,
    ) -> tuple[CapabilityBinding, ...] | None:
        from app.domain.contracts import CapabilityRequirement

        bindings: list[CapabilityBinding] = []
        for requirement in requirements:
            assert isinstance(requirement, CapabilityRequirement)
            if primary is not None and requirement == primary.requirement:
                bindings.append(primary)
                continue
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

    def snapshot_publication(
        self, command_id: str
    ) -> AuthorityReadPublication[ActivityExecutionRecord | None]:
        with self._participant:
            return AuthorityReadPublication(self.snapshot(command_id), (self._participant.token(),))


def _revisions_match(expected: RevisionVector, current: RevisionVector) -> bool:
    if expected.source_context_revision != current.source_context_revision:
        return False
    if expected.goal_revision is not None and expected.goal_revision != current.goal_revision:
        return False
    return (
        expected.attention_revision is None
        or expected.attention_revision == current.attention_revision
    )
