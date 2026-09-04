import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityExecutionCoordinator,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionEffectEvidence,
    ExecutionEffectKind,
    ExecutionEffectUncertainty,
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
    SystemCommand,
)

NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)
REVISIONS = RevisionVector(1)
DISPATCH_ID = "command-1:invocation-1"


def invocation() -> ActivityInvocation:
    command = SystemCommand(
        "command-1",
        "decision-1",
        IntentRef(IntentKind.PLUGIN, "intent-1"),
        AuthorityRef("executive", "conscious_goal_action", "decision-1"),
        NOW,
        REVISIONS,
        preconditions=(PreconditionRef("ready", "equals", "plugin", True),),
        required_capabilities=(CapabilityRequirement("search", "search"),),
    )
    return ActivityInvocation(
        "invocation-1",
        command,
        "plugin.search",
        {"query": "海"},
        ActivityInterruptibility.INTERRUPTIBLE,
        NOW,
    )


def preflight() -> ExecutionPreflightSnapshot:
    return ExecutionPreflightSnapshot(
        REVISIONS,
        (
            CapabilityDescriptor(
                "plugin.search",
                "search",
                ("search",),
                CapabilityAvailability.AVAILABLE,
                2,
                {},
            ),
        ),
        (ExecutionPreconditionState("ready", "plugin", "equals", True),),
        NOW,
    )


def started() -> ActivityExecutionAuthority:
    authority = ActivityExecutionAuthority()
    item = invocation()
    authority.admit(item, preflight())
    authority.start("command-1", preflight(), NOW + timedelta(seconds=1), DISPATCH_ID)
    return authority


def effect() -> ExecutionEffectEvidence:
    return ExecutionEffectEvidence(
        "effect-1",
        "plugin.search",
        2,
        "plugin.search",
        ExecutionEffectKind.APPLIED,
        {"provider": "fake"},
    )


def test_uncertainty_is_closed_and_restricted_to_terminal_failure_reports() -> None:
    with pytest.raises(ValueError, match="終端報告"):
        ExecutionAdapterReport(
            "command-1",
            "invocation-1",
            DISPATCH_ID,
            ExecutionStatus.COMPLETED,
            NOW,
            {},
            effect_uncertainty=ExecutionEffectUncertainty.POSSIBLY_APPLIED,
        )


def test_ambiguous_timeout_records_typed_uncertainty_without_fake_effect_ref() -> None:
    authority = started()
    committed = authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-1",
            DISPATCH_ID,
            ExecutionStatus.TIMED_OUT,
            NOW + timedelta(seconds=2),
            {"code": "provider_timeout"},
            effect_uncertainty=ExecutionEffectUncertainty.POSSIBLY_APPLIED,
        )
    )
    assert committed.result.status is ExecutionStatus.TIMED_OUT
    assert committed.result.effect_refs == ()
    assert committed.record.effect_uncertainty is ExecutionEffectUncertainty.POSSIBLY_APPLIED
    assert (
        committed.lifecycle_facts[-1].effect_uncertainty
        is ExecutionEffectUncertainty.POSSIBLY_APPLIED
    )


def test_confirmed_effect_is_preserved_when_additional_uncertainty_remains() -> None:
    authority = started()
    authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-1",
            DISPATCH_ID,
            ExecutionStatus.APPLIED,
            NOW + timedelta(seconds=2),
            {},
            (effect(),),
        )
    )
    terminal = authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-1",
            DISPATCH_ID,
            ExecutionStatus.TIMED_OUT,
            NOW + timedelta(seconds=3),
            {"code": "followup_timeout"},
            effect_uncertainty=ExecutionEffectUncertainty.UNKNOWN,
        )
    )
    assert terminal.result.effect_refs == ("effect-1",)
    assert terminal.record.effect_uncertainty is ExecutionEffectUncertainty.UNKNOWN


def test_execution_event_projects_effect_uncertainty() -> None:
    authority = started()
    terminal = authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-1",
            DISPATCH_ID,
            ExecutionStatus.CANCELLED,
            NOW + timedelta(seconds=2),
            {"code": "transport_cancelled"},
            effect_uncertainty=ExecutionEffectUncertainty.UNKNOWN,
        )
    )
    event = to_execution_event(
        terminal.record,
        event_id="event-1",
        trace_id="trace-1",
    )
    payload = cast(dict[str, object], event.to_dict()["payload"])
    assert payload["effect_uncertainty"] == "unknown"


class Clock:
    def __init__(self) -> None:
        self.value = NOW + timedelta(seconds=1)

    def now(self) -> datetime:
        value = self.value
        self.value += timedelta(seconds=1)
        return value


class StablePreflight:
    async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
        return preflight()


@pytest.mark.asyncio
async def test_coordinator_records_unknown_when_adapter_raises_after_start() -> None:
    class Port:
        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            raise RuntimeError("provider outcome is unavailable")

    record = await ActivityExecutionCoordinator(
        StablePreflight(), Port(), ActivityExecutionAuthority(), Clock()
    ).execute(invocation())

    assert record.result.status is ExecutionStatus.FAILED
    assert record.result.effect_refs == ()
    assert record.effect_uncertainty is ExecutionEffectUncertainty.UNKNOWN


@pytest.mark.asyncio
async def test_coordinator_records_possible_effect_when_cancelled_after_adapter_start() -> None:
    adapter_started = asyncio.Event()

    class Port:
        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            adapter_started.set()
            await asyncio.Event().wait()
            raise AssertionError("adapter wait unexpectedly completed")

    coordinator = ActivityExecutionCoordinator(
        StablePreflight(), Port(), ActivityExecutionAuthority(), Clock()
    )
    task = asyncio.create_task(coordinator.execute(invocation()))
    await adapter_started.wait()
    task.cancel()
    record = await task

    assert record.result.status is ExecutionStatus.CANCELLED
    assert record.result.effect_refs == ()
    assert record.effect_uncertainty is ExecutionEffectUncertainty.POSSIBLY_APPLIED


@pytest.mark.asyncio
async def test_coordinator_keeps_none_when_cancelled_before_adapter_start() -> None:
    second_preflight_started = asyncio.Event()

    class BlockingPreflight:
        calls = 0

        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            self.calls += 1
            if self.calls == 2:
                second_preflight_started.set()
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

    port = Port()
    coordinator = ActivityExecutionCoordinator(
        BlockingPreflight(), port, ActivityExecutionAuthority(), Clock()
    )
    task = asyncio.create_task(coordinator.execute(invocation()))
    await second_preflight_started.wait()
    task.cancel()
    record = await task

    assert record.result.status is ExecutionStatus.CANCELLED
    assert record.effect_uncertainty is ExecutionEffectUncertainty.NONE
    assert not port.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reports",
    [
        (),
        ("not-a-report",),
        (
            ExecutionAdapterReport(
                "command-1",
                "other-invocation",
                DISPATCH_ID,
                ExecutionStatus.COMPLETED,
                NOW + timedelta(seconds=2),
                {},
            ),
        ),
    ],
)
async def test_coordinator_keeps_unknown_for_adapter_report_contract_failure(
    reports: object,
) -> None:
    class Port:
        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            return cast(Sequence[ExecutionAdapterReport], reports)

    record = await ActivityExecutionCoordinator(
        StablePreflight(), Port(), ActivityExecutionAuthority(), Clock()
    ).execute(invocation())

    assert record.result.status is ExecutionStatus.FAILED
    assert record.result.to_dict()["details"] == {"code": "adapter_contract_failure"}
    assert record.result.effect_refs == ()
    assert record.effect_uncertainty is ExecutionEffectUncertainty.UNKNOWN
