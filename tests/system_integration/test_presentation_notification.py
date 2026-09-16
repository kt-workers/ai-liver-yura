"""Gatewayを再受付させず、実Fact参照と通知の各終端を検証する。"""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from app.composition.execution_observation import (
    SPEECH_OBSERVATION_POLICY,
    SPEECH_OBSERVATION_SOURCE,
)
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.composition.presentation_notification import CorePresentationNotification
from app.composition.presentation_notification import PresentationNotificationState as S
from app.composition.speech_feedback import SpeechFactDeliveryDisposition as Delivery
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityAvailability, ExecutionStatus
from app.domain.executive import GoalTransitionOperation
from app.domain.goals import GoalCommitmentStore
from app.domain.input_gateway import (
    InputAdmission,
    InputModality,
    InputPermission,
    InputSourceState,
)
from app.domain.input_gateway.normalizer import (
    InputAdmissionLedger,
    InputNormalizer,
    InputSessionRegistry,
)
from app.domain.input_meaning import ReferenceContextKind
from tests.domain.activity_execution.test_observation_ingress import observation
from tests.domain.attention.test_attention_response_settlement import prepared_store
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.domain.input_meaning.test_input_meaning import policy


def actual_observation() -> Any:
    initial = observation()
    return replace(
        initial,
        source=SPEECH_OBSERVATION_SOURCE,
        provenance=replace(initial.provenance, source_event_ids=("user-a",)),
        effects=tuple(
            replace(e, effect_type="text-presentation", payload={}) for e in initial.effects
        ),
    )


def ingest(owner: Any, value: Any) -> Any:
    return owner.ingest_observation(
        value, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
    )


def setup(status: ExecutionStatus = ExecutionStatus.COMPLETED) -> tuple[Any, Any, Any]:
    owner = ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
    initial = actual_observation()
    record = ingest(owner, initial)
    if status is not ExecutionStatus.OBSERVABLE:
        record = ingest(
            owner,
            replace(
                initial,
                observation_id="terminal",
                status=status,
                effects=(),
                occurred_at=initial.occurred_at + timedelta(seconds=1),
            ),
        )
    return owner, prepared_store(), record


class Normalizer(InputNormalizer):
    def __init__(self) -> None:
        super().__init__(InputAdmissionLedger(), InputSessionRegistry(), bounds_policy=BOUNDS)
        self.calls = 0

    def normalize(self, observation: Any) -> InputAdmission:
        self.calls += 1
        return super().normalize(observation)


class Submitted:
    accepted = True


def notification(
    monkeypatch: pytest.MonkeyPatch,
    *,
    unavailable: bool = False,
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
) -> tuple[Any, Any, Any, Any]:
    executions, attention, record = setup(status)
    reference = CoreInputReferenceContextBinding(
        GoalCommitmentStore(), executions, policy(), BOUNDS
    )
    normalizer = Normalizer()
    admissions: list[InputAdmission] = []

    def submit(admission: InputAdmission, root: str) -> Any:
        admissions.append(admission)
        assert root == "root"
        return Submitted()

    delivery = CorePresentationNotification(
        executions,
        attention,
        reference,
        normalizer,
        InputSourceState(
            "speech-feedback",
            "subsystem",
            CapabilityAvailability.UNAVAILABLE if unavailable else CapabilityAvailability.AVAILABLE,
            InputPermission.NOT_REQUIRED,
        ),
        record.provenance,
        "root",
        record.execution_id,
        submit,
    )
    return delivery, record, admissions, normalizer


def test_normalize_terminal_reject_keeps_fact_and_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d, r, submitted, n = notification(monkeypatch, unavailable=True)
    d.deliver(r)
    after = d.attention.snapshot()
    assert after.current_turn_owner is None and after.response_obligation is None
    assert d.state is S.TERMINAL_REJECTED
    d.source = replace(d.source, availability=CapabilityAvailability.AVAILABLE)
    d.deliver(r)
    assert n.calls == 1 and submitted == [] and d.attention.snapshot() is after
    ref = d.reference.snapshot()
    assert any(
        e.kind is ReferenceContextKind.PRESENTATION_FACT and e.subject_ref == r.subject_ref
        for e in ref.context.entries
    )
    assert all(
        e.kind is not ReferenceContextKind.ACTUAL_EXECUTION_FACT for e in ref.context.entries
    )
    assert d.authority.observed_snapshot(r.source.source_contract_id, r.execution_id).value == r


def test_cached_exact_admission_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    d, r, submitted, n = notification(monkeypatch)
    original = d.submit_input
    attempts = []

    def fail_first(a: InputAdmission, root: str) -> Any:
        attempts.append(a)
        if len(attempts) == 1:
            raise ValueError("同期受付失敗")
        return original(a, root)

    d.submit_input = fail_first
    assert d.deliver(r) is Delivery.RETRY
    assert isinstance(d.last_error, ValueError)
    assert str(d.last_error) == "同期受付失敗"
    settled = d.attention.snapshot()
    d.deliver(r)
    d.deliver(r)
    assert d.state is S.SUBMITTED and n.calls == 1 and len(submitted) == 1
    assert attempts[0] is attempts[1] is submitted[0]
    assert d.attention.snapshot() is settled
    assert submitted[0].event is not None
    assert submitted[0].event.modality is InputModality.SUBSYSTEM
    assert submitted[0].event.envelope.event_type == "input.subsystem.presentation_fact"


def test_stale_cached_admission_never_upgrades(monkeypatch: pytest.MonkeyPatch) -> None:
    d, r, submitted, n = notification(monkeypatch)

    def failure(a: InputAdmission, root: str) -> Any:
        raise ValueError("同期失敗")

    d.submit_input = failure
    assert d.deliver(r) is Delivery.RETRY
    assert isinstance(d.last_error, ValueError)
    admission = d.admission
    apply_goal(d.reference._goals, GoalTransitionOperation.CREATE, 0)
    d.deliver(r)
    assert d.state is S.STALE and n.calls == 1 and d.admission is admission
    assert submitted == []
    assert (
        d.reference.snapshot().context.source_context_revision
        != admission.event.envelope.revisions.source_context_revision
    )


def test_submitted_and_payload_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    d, r, submitted, n = notification(monkeypatch)
    d.deliver(r)
    d.deliver(r)
    assert len(submitted) == n.calls == 1
    payload = submitted[0].event.envelope.payload
    assert "speech_text" not in repr(payload) and "asset" not in repr(payload)
    assert "presentation_fact_id" in repr(payload)


def test_mismatched_decision_is_integrity_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    d, r, submitted, n = notification(monkeypatch)
    d.provenance = replace(d.provenance, source_decision_id="other")
    before = d.attention.snapshot()
    with pytest.raises(ValueError, match="相関"):
        d.deliver(r)
    assert n.calls == 0 and submitted == [] and d.attention.snapshot() is before


@pytest.mark.parametrize(
    "status", [ExecutionStatus.OBSERVABLE, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]
)
def test_non_completed_preserves_turn_and_notifies(
    monkeypatch: pytest.MonkeyPatch, status: ExecutionStatus
) -> None:
    d, r, submitted, n = notification(monkeypatch, status=status)
    before = d.attention.snapshot()
    d.deliver(r)
    assert d.attention.snapshot() is before
    assert n.calls == len(submitted) == 1
    assert submitted[0].event.envelope.payload["content"]["status"] == status.value


def test_old_record_is_not_upgraded_and_reference_tracks_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d, old, submitted, n = notification(monkeypatch, status=ExecutionStatus.OBSERVABLE)
    d.deliver(old)
    before = d.reference.snapshot()
    initial = actual_observation()
    terminal = ingest(
        d.authority,
        replace(
            initial,
            observation_id="terminal",
            status=ExecutionStatus.COMPLETED,
            effects=(),
            occurred_at=initial.occurred_at + timedelta(seconds=1),
        ),
    )
    current = d.reference.snapshot()
    assert current.context.source_context_revision > before.context.source_context_revision
    assert (
        sum(e.kind is ReferenceContextKind.PRESENTATION_FACT for e in current.context.entries) == 1
    )
    d.deliver(old)
    assert n.calls == len(submitted) == 1
    d.deliver(terminal)
    assert n.calls == len(submitted) == 2
    assert submitted[0].event.envelope.event_id != submitted[1].event.envelope.event_id
    assert submitted[0].event.envelope.trace_id == submitted[1].event.envelope.trace_id == "trace"


def test_owner_target_rejection_keeps_unrelated_turn_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d, r, submitted, n = notification(monkeypatch)
    from tests.domain.attention.test_attention_turn_store import attention_store

    d.attention = attention_store()
    before = d.attention.snapshot()
    d.deliver(r)
    assert d.attention.snapshot() is before
    assert n.calls == len(submitted) == 1


@pytest.mark.parametrize("changed_owner", ["source", "attention"])
def test_finalization_race_returns_retry_without_normalizing(
    monkeypatch: pytest.MonkeyPatch, changed_owner: str
) -> None:
    from app.domain.contracts.finalization import FinalizationError, FinalizationFailure
    from app.usecases.attention import AttentionResponseSettlementCoordinator
    from tests.domain.attention.test_attention_turn_store import signal

    d, r, submitted, n = notification(monkeypatch)
    original = AttentionResponseSettlementCoordinator.prepare

    def prepare(self: Any, *args: Any, **kwargs: Any) -> Any:
        request = original(self, *args, **kwargs)
        if changed_owner == "source":
            ingest(
                d.authority,
                replace(actual_observation(), execution_id="other", observation_id="other"),
            )
        else:
            d.attention.offer(signal("new-source", revision=2, seconds=30))
        return request

    monkeypatch.setattr(AttentionResponseSettlementCoordinator, "prepare", prepare)
    assert d.deliver(r) is Delivery.RETRY
    assert isinstance(d.last_error, FinalizationError)
    assert d.last_error.failure is FinalizationFailure.GENERATION_MISMATCH
    assert d.attention.snapshot().current_turn_owner is not None
    assert n.calls == 0 and submitted == []
    monkeypatch.setattr(AttentionResponseSettlementCoordinator, "prepare", original)
    d.deliver(r)
    assert n.calls == len(submitted) == 1


def test_wrong_presentation_identity_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    d, r, submitted, n = notification(monkeypatch)
    d.presentation_id = "other-presentation"
    with pytest.raises(ValueError, match="相関"):
        d.deliver(r)
    assert n.calls == 0 and submitted == []


class GoalSnapshotSource:
    """正規Owner由来のsnapshotが縮小する場合も含めた読取fixture。"""

    def __init__(self, count: int) -> None:
        store = GoalCommitmentStore()
        for i in range(count):
            apply_goal(store, GoalTransitionOperation.CREATE, i, goal_id=f"goal-{i}")
        self.value = store.snapshot()

    def snapshot(self) -> Any:
        return self.value


def test_exact_capacity_failure_is_atomic_and_retry_does_not_consume_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.composition.input_reference_context import PresentationReferenceCapacityError

    d, r, submitted, normalizer = notification(monkeypatch)
    goals = GoalSnapshotSource(32)
    d.reference = CoreInputReferenceContextBinding(goals, d.authority, policy(), BOUNDS)
    before = d.reference.snapshot()
    assert len(before.context.entries) == 32 and before.context.max_entries == 32
    owner_before = d.authority.observed_snapshot(r.source.source_contract_id, r.execution_id)
    with pytest.raises(PresentationReferenceCapacityError):
        d.reference.set_presentation_reference(r)
    assert d.reference._presentation is None
    assert d.reference.snapshot() is before
    assert d.deliver(r) is Delivery.RETRY
    assert normalizer.calls == 0 and d.admission is None and submitted == []
    assert d.reference.snapshot() is before
    assert (
        d.authority.observed_snapshot(r.source.source_contract_id, r.execution_id) == owner_before
    )

    # 読取元が次の正規revisionで縮小した場合、同じFact/identityで登録を再試行する。
    goals.value = replace(goals.value, revision=33, goals=goals.value.goals[:-1])
    assert d.deliver(r) is Delivery.DELIVERED
    current = d.reference.snapshot()
    assert len(current.context.entries) == 32
    assert (
        sum(e.kind is ReferenceContextKind.PRESENTATION_FACT for e in current.context.entries) == 1
    )
    assert normalizer.calls == len(submitted) == 1
    assert d.deliver(r) is Delivery.TERMINAL
    assert normalizer.calls == 1


@pytest.mark.parametrize("activity_count", [1, 2])
def test_presentation_evicts_only_oldest_activity_reference(
    monkeypatch: pytest.MonkeyPatch, activity_count: int
) -> None:
    from tests.domain.activity_execution.test_activity_execution import NOW, invocation, preflight

    d, r, _, _ = notification(monkeypatch)
    goals = GoalSnapshotSource(32 - activity_count)
    d.reference = CoreInputReferenceContextBinding(goals, d.authority, policy(), BOUNDS)
    commands = tuple(f"activity-{i}" for i in range(activity_count))
    for i, command_id in enumerate(commands):
        d.authority.admit(invocation(command_id), preflight())
        d.authority.start(command_id, preflight(), NOW + timedelta(seconds=1), f"dispatch-{i}")
    d.reference.set_activity_references(commands)
    before = d.reference.snapshot()
    owner_records = tuple(d.authority.snapshot(k) for k in commands)
    assert len(before.context.entries) == 32
    d.reference.set_presentation_reference(r)
    after = d.reference.snapshot()
    assert after.goals == before.goals
    assert len(after.context.entries) == 32
    assert tuple(v.result.command_id for v in after.activities) == commands[1:]
    assert tuple(d.authority.snapshot(k) for k in commands) == owner_records
    assert sum(e.kind is ReferenceContextKind.PRESENTATION_FACT for e in after.context.entries) == 1
    assert {
        e.subject_ref
        for e in after.context.entries
        if e.kind is ReferenceContextKind.GOAL_COMMITMENT
    } == {g.goal_id for g in goals.value.goals}
