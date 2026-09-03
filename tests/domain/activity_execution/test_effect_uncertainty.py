from datetime import datetime, timedelta, timezone

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionAdapterReport,
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
    with pytest.raises(ValueError, match="terminal failure"):
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
    assert committed.lifecycle_facts[-1].effect_uncertainty is ExecutionEffectUncertainty.POSSIBLY_APPLIED


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
    assert event.to_dict()["payload"]["effect_uncertainty"] == "unknown"
