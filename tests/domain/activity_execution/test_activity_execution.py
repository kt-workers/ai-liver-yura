import asyncio
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityExecutionCoordinator,
    ActivityExecutionRecord,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionEffectEvidence,
    ExecutionEffectKind,
    ExecutionPreconditionState,
    ExecutionPreflightSnapshot,
    to_execution_event,
)
from app.domain.contracts import (
    AuthorityRef,
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
    ExecutionStatus,
    IntentKind,
    IntentRef,
    PreconditionRef,
    RevisionVector,
    SourceLifecycleOperation,
    SystemCommand,
)
from app.domain.contracts.common import JsonValue

NOW = datetime(2026, 8, 14, 3, tzinfo=timezone.utc)
REVISIONS = RevisionVector(7, 5, 3)
DISPATCH_ID = "command-1:invocation-command-1"


def command(
    command_id: str = "command-1",
    *,
    revisions: RevisionVector = REVISIONS,
    deadline_at: datetime | None = None,
) -> SystemCommand:
    return SystemCommand(
        command_id,
        "decision-1",
        IntentRef(IntentKind.ACTIVITY, "intent-1"),
        AuthorityRef("executive", "conscious_goal_action", "decision-1"),
        NOW,
        revisions,
        deadline_at,
        (PreconditionRef("pre-ready", "equals", "activity", "ready"),),
        (CapabilityRequirement("activity", "run"),),
    )


def invocation(
    command_id: str = "command-1",
    *,
    invocation_id: str | None = None,
    interruptibility: ActivityInterruptibility = ActivityInterruptibility.INTERRUPTIBLE,
    deadline_at: datetime | None = None,
) -> ActivityInvocation:
    return ActivityInvocation(
        invocation_id or f"invocation-{command_id}",
        command(command_id, deadline_at=deadline_at),
        "activity.run",
        {"target_ref": "target-1"},
        interruptibility,
        NOW,
    )


def capability(
    *,
    availability: CapabilityAvailability = CapabilityAvailability.AVAILABLE,
    revision: int = 2,
) -> CapabilityDescriptor:
    return CapabilityDescriptor("capability-1", "activity", ("run",), availability, revision, {})


def preflight(
    *,
    revisions: RevisionVector = REVISIONS,
    capabilities: tuple[CapabilityDescriptor, ...] | None = None,
    preconditions: tuple[ExecutionPreconditionState, ...] | None = None,
    captured_at: datetime = NOW,
) -> ExecutionPreflightSnapshot:
    return ExecutionPreflightSnapshot(
        revisions,
        (capability(),) if capabilities is None else capabilities,
        (ExecutionPreconditionState("pre-ready", "activity", "equals", "ready"),)
        if preconditions is None
        else preconditions,
        captured_at,
    )


def started(
    authority: ActivityExecutionAuthority | None = None,
) -> tuple[ActivityExecutionAuthority, ActivityExecutionRecord]:
    owner = authority or ActivityExecutionAuthority()
    item = invocation()
    owner.admit(item, preflight())
    record = owner.start(
        item.command.command_id, preflight(), NOW + timedelta(seconds=1), DISPATCH_ID
    )
    return owner, record


def effect(
    effect_id: str = "effect-1",
    *,
    kind: ExecutionEffectKind = ExecutionEffectKind.APPLIED,
    capability_id: str = "capability-1",
    descriptor_revision: int = 2,
    operation_ref: str = "activity.run",
) -> ExecutionEffectEvidence:
    return ExecutionEffectEvidence(
        effect_id,
        capability_id,
        descriptor_revision,
        operation_ref,
        kind,
        {"evidence": "adapter"},
    )


def test_invocation_is_typed_immutable_and_rejects_non_executable_intent() -> None:
    raw = {"nested": ["owned"]}
    value = ActivityInvocation(
        "invocation-1",
        command(),
        "activity.run",
        cast(JsonValue, raw),
        ActivityInterruptibility.INTERRUPTIBLE,
        NOW,
    )
    raw["nested"].append("mutated")
    assert value.to_dict()["arguments"] == {"nested": ["owned"]}
    attention = replace(command(), intent_ref=IntentRef(IntentKind.ATTENTION, "focus"))
    with pytest.raises(ValueError, match="not executable"):
        replace(value, command=attention)


def test_admission_binds_current_capability_and_accepts_valid_command() -> None:
    record = ActivityExecutionAuthority().admit(invocation(), preflight())
    assert record.result.status is ExecutionStatus.ACCEPTED
    assert record.bindings[0].capability_id == "capability-1"
    assert record.bindings[0].descriptor_revision == 2


def test_activity_owner_facts_carry_requested_open_and_execution_lifecycle() -> None:
    authority = ActivityExecutionAuthority()
    accepted = authority.admit(invocation(), preflight())
    opened, admitted = authority.lifecycle_facts()
    assert opened.operation is SourceLifecycleOperation.OPEN
    assert opened.status is ExecutionStatus.REQUESTED
    assert admitted.operation is SourceLifecycleOperation.REFRESH
    assert admitted.expected_source_revision == opened.source_revision
    started_record = authority.start(
        accepted.result.command_id, preflight(), NOW + timedelta(seconds=1), DISPATCH_ID
    )
    started_fact = authority.lifecycle_facts()[-1]
    assert started_record.record_revision == started_fact.source_revision
    assert started_fact.operation is SourceLifecycleOperation.REFRESH
    completed = authority.apply_report(
        ExecutionAdapterReport(
            accepted.result.command_id,
            accepted.invocation.invocation_id,
            DISPATCH_ID,
            ExecutionStatus.COMPLETED,
            NOW + timedelta(seconds=2),
            {},
        )
    )
    closed = authority.lifecycle_facts()[-1]
    assert completed.terminal is True
    assert closed.operation is SourceLifecycleOperation.CLOSE
    assert closed.expected_source_revision == completed.record_revision - 1


def test_command_authority_reference_must_match_decision() -> None:
    item = invocation()
    forged = replace(
        item.command,
        authority=AuthorityRef("executive", "conscious_goal_action", "other-decision"),
    )
    with pytest.raises(ValueError, match="authority reference"):
        ActivityExecutionAuthority().admit(replace(item, command=forged), preflight())


def test_missing_capability_is_unsupported_and_degraded_requires_permission() -> None:
    unavailable = ActivityExecutionAuthority().admit(invocation(), preflight(capabilities=()))
    assert unavailable.result.status is ExecutionStatus.UNSUPPORTED
    degraded = preflight(capabilities=(capability(availability=CapabilityAvailability.DEGRADED),))
    rejected = ActivityExecutionAuthority().admit(invocation(), degraded)
    assert rejected.result.status is ExecutionStatus.UNSUPPORTED

    allowed_command = replace(
        command(),
        required_capabilities=(CapabilityRequirement("activity", "run", True),),
    )
    allowed = replace(invocation(), command=allowed_command)
    assert (
        ActivityExecutionAuthority().admit(allowed, degraded).result.status
        is ExecutionStatus.ACCEPTED
    )


@pytest.mark.parametrize(
    "current",
    [
        preflight(revisions=RevisionVector(8, 5, 3)),
        preflight(revisions=RevisionVector(7, 6, 3)),
        preflight(revisions=RevisionVector(7, 5, 4)),
    ],
)
def test_stale_revision_is_rejected_before_admission(
    current: ExecutionPreflightSnapshot,
) -> None:
    record = ActivityExecutionAuthority().admit(invocation(), current)
    assert record.result.status is ExecutionStatus.SUPERSEDED


@pytest.mark.parametrize(
    "state",
    [
        ExecutionPreconditionState("pre-ready", "other", "equals", "ready"),
        ExecutionPreconditionState("pre-ready", "activity", "not_equals", "ready"),
        ExecutionPreconditionState("pre-ready", "activity", "equals", "busy"),
    ],
)
def test_precondition_identity_and_actual_are_revalidated(
    state: ExecutionPreconditionState,
) -> None:
    record = ActivityExecutionAuthority().admit(invocation(), preflight(preconditions=(state,)))
    assert record.result.status is ExecutionStatus.REJECTED


def test_dispatch_revalidation_rejects_changed_capability_revision() -> None:
    authority = ActivityExecutionAuthority()
    item = invocation()
    authority.admit(item, preflight())
    record = authority.start(
        item.command.command_id,
        preflight(capabilities=(capability(revision=3),)),
        NOW + timedelta(seconds=1),
        DISPATCH_ID,
    )
    assert record.result.status is ExecutionStatus.SUPERSEDED


def test_deadline_is_checked_before_start() -> None:
    deadline = NOW + timedelta(seconds=2)
    authority = ActivityExecutionAuthority()
    item = invocation(deadline_at=deadline)
    authority.admit(item, preflight())
    record = authority.start(item.command.command_id, preflight(), deadline, DISPATCH_ID)
    assert record.result.status is ExecutionStatus.TIMED_OUT


def test_preflight_older_than_command_is_stale() -> None:
    record = ActivityExecutionAuthority().admit(
        invocation(), preflight(captured_at=NOW - timedelta(seconds=1))
    )
    assert record.result.status is ExecutionStatus.SUPERSEDED


def test_adapter_reports_create_validated_actual_fact_lifecycle() -> None:
    authority, record = started()
    assert record.result.status is ExecutionStatus.STARTED
    applied = authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-command-1",
            DISPATCH_ID,
            ExecutionStatus.APPLIED,
            NOW + timedelta(seconds=2),
            {"code": "applied"},
            (effect(),),
        )
    )
    completed = authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-command-1",
            DISPATCH_ID,
            ExecutionStatus.COMPLETED,
            NOW + timedelta(seconds=3),
            {"code": "completed"},
        )
    )
    assert applied.result.effect_refs == ("effect-1",)
    assert completed.result.status is ExecutionStatus.COMPLETED
    assert completed.result.effect_refs == ("effect-1",)


def test_report_identity_illegal_edge_and_timestamp_fail_closed() -> None:
    authority, _ = started()
    with pytest.raises(ValueError, match="invocation"):
        authority.apply_report(
            ExecutionAdapterReport(
                "command-1",
                "other",
                DISPATCH_ID,
                ExecutionStatus.COMPLETED,
                NOW + timedelta(seconds=2),
                {},
            )
        )
    with pytest.raises(ValueError, match="backwards"):
        authority.apply_report(
            ExecutionAdapterReport(
                "command-1",
                "invocation-command-1",
                DISPATCH_ID,
                ExecutionStatus.COMPLETED,
                NOW,
                {},
            )
        )


def test_effect_is_preserved_when_execution_becomes_stale_after_apply() -> None:
    authority, _ = started()
    authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-command-1",
            DISPATCH_ID,
            ExecutionStatus.APPLIED,
            NOW + timedelta(seconds=2),
            {},
            (effect("external-effect"),),
        )
    )
    stale = authority.supersede("command-1", NOW + timedelta(seconds=3))
    assert stale.result.status is ExecutionStatus.SUPERSEDED
    assert stale.result.effect_refs == ("external-effect",)


def test_actual_execution_fact_projects_to_bounded_foundation_event() -> None:
    authority, _ = started()
    record = authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-command-1",
            DISPATCH_ID,
            ExecutionStatus.COMPLETED,
            NOW + timedelta(seconds=2),
            {"outcome": "done"},
            (effect(),),
        )
    )
    event = to_execution_event(record, event_id="event-execution-1", trace_id="trace-1")
    assert event.event_type == "execution.completed"
    assert event.source == "activity_execution"
    assert event.revisions == REVISIONS
    assert event.to_dict()["payload"] == {
        "command_id": "command-1",
        "invocation_id": "invocation-command-1",
        "decision_id": "decision-1",
        "intent_id": "intent-1",
        "operation_ref": "activity.run",
        "status": "completed",
        "effect_refs": ["effect-1"],
        "details": {"outcome": "done"},
        "cancellation_reason": None,
        "cancellation_requested_at": None,
    }


def test_duplicate_command_and_invocation_are_atomic() -> None:
    authority = ActivityExecutionAuthority()

    def attempt(index: int) -> str:
        try:
            authority.admit(invocation(), preflight())
            return "accepted"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, range(2)))
    assert outcomes.count("accepted") == 1
    assert outcomes.count("rejected") == 1


def test_cancellation_before_start_is_terminal_and_idempotent() -> None:
    authority = ActivityExecutionAuthority()
    authority.admit(invocation(), preflight())
    cancelled = authority.request_cancellation(
        "command-1", "user_cancelled", NOW + timedelta(seconds=1)
    )
    repeated = authority.request_cancellation(
        "command-1", "different_reason", NOW + timedelta(seconds=2)
    )
    assert cancelled.result.status is ExecutionStatus.CANCELLED
    assert repeated == cancelled
    assert repeated.cancellation_reason == "user_cancelled"


class Clock:
    def __init__(self) -> None:
        self.value = NOW + timedelta(seconds=1)

    def now(self) -> datetime:
        value = self.value
        self.value += timedelta(seconds=1)
        return value


@pytest.mark.asyncio
async def test_coordinator_reads_live_preflight_again_after_admission() -> None:
    class Preflight:
        calls = 0

        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            self.calls += 1
            return preflight(capabilities=(capability(revision=2 if self.calls == 1 else 3),))

    class Port:
        called = False

        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            self.called = True
            return ()

    port = Port()
    coordinator = ActivityExecutionCoordinator(
        Preflight(), port, ActivityExecutionAuthority(), Clock()
    )
    record = await coordinator.execute(invocation())
    assert record.result.status is ExecutionStatus.SUPERSEDED
    assert not port.called


@pytest.mark.asyncio
async def test_slow_activity_does_not_block_unrelated_activity() -> None:
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()

    class Preflight:
        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            return preflight()

    class Port:
        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            command_id = request.invocation.command.command_id
            if command_id == "slow":
                slow_started.set()
                await release_slow.wait()
            return (
                ExecutionAdapterReport(
                    command_id,
                    request.invocation.invocation_id,
                    request.dispatch_id,
                    ExecutionStatus.COMPLETED,
                    NOW + timedelta(seconds=10),
                    {},
                ),
            )

    coordinator = ActivityExecutionCoordinator(
        Preflight(), Port(), ActivityExecutionAuthority(), Clock()
    )
    slow = asyncio.create_task(coordinator.execute(invocation("slow")))
    await slow_started.wait()
    fast = await asyncio.wait_for(coordinator.execute(invocation("fast")), timeout=0.2)
    assert fast.result.status is ExecutionStatus.COMPLETED
    release_slow.set()
    assert (await slow).result.status is ExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_adapter_exception_is_sanitized_and_does_not_leak_payload() -> None:
    class Preflight:
        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            return preflight()

    class Port:
        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            raise RuntimeError("credential=secret payload=private")

    record = await ActivityExecutionCoordinator(
        Preflight(), Port(), ActivityExecutionAuthority(), Clock()
    ).execute(invocation())
    assert record.result.status is ExecutionStatus.FAILED
    assert record.result.to_dict()["details"] == {"code": "adapter_failure"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("interruptibility", "expected"),
    [
        (ActivityInterruptibility.INTERRUPTIBLE, ExecutionStatus.CANCELLED),
        (ActivityInterruptibility.NON_INTERRUPTIBLE, ExecutionStatus.COMPLETED),
        (ActivityInterruptibility.SOFT_CANCEL_ONLY, ExecutionStatus.COMPLETED),
    ],
)
async def test_outer_task_cancellation_respects_interruptibility(
    interruptibility: ActivityInterruptibility, expected: ExecutionStatus
) -> None:
    started_event = asyncio.Event()
    release = asyncio.Event()

    class Preflight:
        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            return preflight()

    class Port:
        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            started_event.set()
            await release.wait()
            return (
                ExecutionAdapterReport(
                    request.invocation.command.command_id,
                    request.invocation.invocation_id,
                    request.dispatch_id,
                    ExecutionStatus.COMPLETED,
                    NOW + timedelta(seconds=10),
                    {},
                ),
            )

    coordinator = ActivityExecutionCoordinator(
        Preflight(), Port(), ActivityExecutionAuthority(), Clock()
    )
    task = asyncio.create_task(coordinator.execute(invocation(interruptibility=interruptibility)))
    await started_event.wait()
    task.cancel()
    await asyncio.sleep(0)
    if interruptibility is not ActivityInterruptibility.INTERRUPTIBLE:
        assert not task.done()
    release.set()
    assert (await task).result.status is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("interruptibility", "expected"),
    [
        (ActivityInterruptibility.INTERRUPTIBLE, ExecutionStatus.CANCELLED),
        (ActivityInterruptibility.SOFT_CANCEL_ONLY, ExecutionStatus.COMPLETED),
        (ActivityInterruptibility.NON_INTERRUPTIBLE, ExecutionStatus.COMPLETED),
    ],
)
async def test_explicit_cancellation_signal_preserves_soft_and_noninterruptible_effects(
    interruptibility: ActivityInterruptibility, expected: ExecutionStatus
) -> None:
    port_started = asyncio.Event()

    class Preflight:
        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            return preflight()

    class Port:
        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            port_started.set()
            while not cancellation.cancelled:
                await asyncio.sleep(0)
            if cancellation.hard_interrupt_allowed:
                return (
                    ExecutionAdapterReport(
                        request.invocation.command.command_id,
                        request.invocation.invocation_id,
                        request.dispatch_id,
                        ExecutionStatus.CANCELLED,
                        NOW + timedelta(seconds=10),
                        {"code": "cancelled"},
                    ),
                )
            return (
                ExecutionAdapterReport(
                    request.invocation.command.command_id,
                    request.invocation.invocation_id,
                    request.dispatch_id,
                    ExecutionStatus.COMPLETED,
                    NOW + timedelta(seconds=10),
                    {"code": "late_completion"},
                    (effect("effect-after-cancel"),),
                ),
            )

    coordinator = ActivityExecutionCoordinator(
        Preflight(), Port(), ActivityExecutionAuthority(), Clock()
    )
    task = asyncio.create_task(coordinator.execute(invocation(interruptibility=interruptibility)))
    await port_started.wait()
    requested = await coordinator.cancel("command-1", "user_cancelled")
    assert requested.cancellation_reason == "user_cancelled"
    result = await task
    assert result.result.status is expected
    if expected is ExecutionStatus.COMPLETED:
        assert result.result.effect_refs == ("effect-after-cancel",)


def test_completion_after_deadline_becomes_timed_out_and_preserves_valid_effect() -> None:
    deadline = NOW + timedelta(seconds=3)
    authority = ActivityExecutionAuthority()
    item = invocation(deadline_at=deadline)
    authority.admit(item, preflight())
    authority.start("command-1", preflight(), NOW + timedelta(seconds=1), DISPATCH_ID)
    record = authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-command-1",
            DISPATCH_ID,
            ExecutionStatus.COMPLETED,
            deadline + timedelta(seconds=1),
            {"code": "late"},
            (effect("late-effect"),),
        )
    )
    assert record.result.status is ExecutionStatus.TIMED_OUT
    assert record.result.effect_refs == ("late-effect",)
    assert record.result.to_dict()["details"] == {"code": "deadline_elapsed"}


@pytest.mark.parametrize(
    ("first_status", "first_kind"),
    [
        (ExecutionStatus.OBSERVABLE, ExecutionEffectKind.OBSERVABLE),
        (ExecutionStatus.APPLIED, ExecutionEffectKind.APPLIED),
    ],
)
def test_new_effect_after_existing_milestone_and_deadline_is_preserved(
    first_status: ExecutionStatus, first_kind: ExecutionEffectKind
) -> None:
    deadline = NOW + timedelta(seconds=4)
    authority = ActivityExecutionAuthority()
    item = invocation(deadline_at=deadline)
    authority.admit(item, preflight())
    authority.start("command-1", preflight(), NOW + timedelta(seconds=1), DISPATCH_ID)
    authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-command-1",
            DISPATCH_ID,
            first_status,
            NOW + timedelta(seconds=2),
            {},
            (effect("effect-before", kind=first_kind),),
        )
    )
    record = authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-command-1",
            DISPATCH_ID,
            ExecutionStatus.COMPLETED,
            deadline + timedelta(seconds=1),
            {},
            (effect("effect-after", kind=ExecutionEffectKind.APPLIED),),
        )
    )
    assert record.result.status is ExecutionStatus.TIMED_OUT
    assert record.result.effect_refs == ("effect-before", "effect-after")


@pytest.mark.parametrize(
    ("dispatch_id", "evidence", "message"),
    [
        ("other-dispatch", effect(), "dispatch"),
        (DISPATCH_ID, effect(capability_id="other-capability"), "capability"),
        (DISPATCH_ID, effect(descriptor_revision=3), "capability"),
        (DISPATCH_ID, effect(operation_ref="other.operation"), "operation"),
    ],
)
def test_report_effect_is_grounded_to_dispatch_binding_and_operation(
    dispatch_id: str, evidence: ExecutionEffectEvidence, message: str
) -> None:
    authority, _ = started()
    with pytest.raises(ValueError, match=message):
        authority.apply_report(
            ExecutionAdapterReport(
                "command-1",
                "invocation-command-1",
                dispatch_id,
                ExecutionStatus.COMPLETED,
                NOW + timedelta(seconds=2),
                {},
                (evidence,),
            )
        )
    assert authority.snapshot("command-1").result.effect_refs == ()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_cancel_during_second_preflight_converges_without_adapter_call() -> None:
    blocked = asyncio.Event()
    release = asyncio.Event()

    class Preflight:
        calls = 0

        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            self.calls += 1
            if self.calls == 2:
                blocked.set()
                await release.wait()
            return preflight()

    class Port:
        called = False

        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            self.called = True
            return ()

    authority = ActivityExecutionAuthority()
    port = Port()
    coordinator = ActivityExecutionCoordinator(Preflight(), port, authority, Clock())
    task = asyncio.create_task(coordinator.execute(invocation()))
    await blocked.wait()
    await coordinator.cancel("command-1", "user_cancelled")
    release.set()
    record = await task
    assert record.result.status is ExecutionStatus.CANCELLED
    assert not port.called


@pytest.mark.asyncio
async def test_outer_cancel_during_second_preflight_leaves_no_accepted_orphan() -> None:
    blocked = asyncio.Event()

    class Preflight:
        calls = 0

        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            self.calls += 1
            if self.calls == 2:
                blocked.set()
                await asyncio.Event().wait()
            return preflight()

    class Port:
        called = False

        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            self.called = True
            return ()

    authority = ActivityExecutionAuthority()
    port = Port()
    coordinator = ActivityExecutionCoordinator(Preflight(), port, authority, Clock())
    task = asyncio.create_task(coordinator.execute(invocation()))
    await blocked.wait()
    task.cancel()
    record = await task
    assert record.result.status is ExecutionStatus.CANCELLED
    assert authority.snapshot("command-1") == record
    assert not port.called


@pytest.mark.asyncio
async def test_explicit_cancel_hard_cancels_noncooperative_interruptible_adapter() -> None:
    adapter_started = asyncio.Event()
    hard_cancelled = asyncio.Event()

    class Preflight:
        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            return preflight()

    class Port:
        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            adapter_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                hard_cancelled.set()
                raise
            raise AssertionError("adapter wait unexpectedly completed")

    coordinator = ActivityExecutionCoordinator(
        Preflight(), Port(), ActivityExecutionAuthority(), Clock()
    )
    task = asyncio.create_task(coordinator.execute(invocation()))
    await adapter_started.wait()
    await coordinator.cancel("command-1", "user_cancelled")
    record = await task
    assert hard_cancelled.is_set()
    assert record.result.status is ExecutionStatus.CANCELLED


@pytest.mark.asyncio
@pytest.mark.parametrize("reports", [(), ("not-a-report",)])
async def test_malformed_adapter_output_becomes_typed_failure(reports: object) -> None:
    class Preflight:
        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            return preflight()

    class Port:
        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            return cast(Sequence[ExecutionAdapterReport], reports)

    record = await ActivityExecutionCoordinator(
        Preflight(), Port(), ActivityExecutionAuthority(), Clock()
    ).execute(invocation())
    assert record.result.status is ExecutionStatus.FAILED
    assert record.result.to_dict()["details"] == {"code": "adapter_contract_failure"}
