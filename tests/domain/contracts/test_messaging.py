from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.domain.contracts import (
    AuthorityRef,
    CapabilityRequirement,
    EventEnvelope,
    ExecutiveDecision,
    IntentKind,
    IntentRef,
    PreconditionRef,
    RevisionVector,
    SystemCommand,
)

NOW = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)


def revisions() -> RevisionVector:
    return RevisionVector(2, goal_revision=3, attention_revision=4)


def authority() -> AuthorityRef:
    return AuthorityRef("executive", "activity", "decision-1")


def intent() -> IntentRef:
    return IntentRef(IntentKind.ACTIVITY, "intent-1")


def test_event_owns_payload_and_serializes_trace_context() -> None:
    items = ["one"]
    event = EventEnvelope(
        "event-1",
        "user.message.received",
        "input.gateway",
        NOW,
        "trace-1",
        revisions(),
        {"items": items},  # type: ignore[dict-item]
        correlation_id="conversation-1",
        causation_event_id="event-0",
    )
    items.append("two")

    assert event.to_dict() == {
        "event_id": "event-1",
        "event_type": "user.message.received",
        "source": "input.gateway",
        "occurred_at": NOW.isoformat(),
        "trace_id": "trace-1",
        "correlation_id": "conversation-1",
        "causation_event_id": "event-0",
        "revisions": revisions().to_dict(),
        "payload": {"items": ["one"]},
    }


def test_event_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EventEnvelope("e", "type", "source", datetime.now(), "trace", revisions(), {})


def test_event_rejects_invalid_top_level_json() -> None:
    with pytest.raises(ValueError, match="keys must be strings"):
        EventEnvelope("e", "type", "source", NOW, "trace", revisions(), {1: "bad"})  # type: ignore[dict-item]


def test_executive_decision_owns_tuple_fields() -> None:
    source_ids = ["event-1"]
    intents = [intent()]
    decision = ExecutiveDecision(
        "decision-1", source_ids, intents, authority(), revisions(), NOW  # type: ignore[arg-type]
    )
    source_ids.append("event-2")
    intents.clear()

    assert decision.source_event_ids == ("event-1",)
    assert decision.intent_refs == (intent(),)
    assert decision.to_dict()["created_at"] == NOW.isoformat()


def test_executive_decision_rejects_duplicate_source_events() -> None:
    with pytest.raises(ValueError, match="unique"):
        ExecutiveDecision(
            "decision-1", ("event-1", "event-1"), (), authority(), revisions(), NOW
        )


def test_command_owns_preconditions_and_requirements_and_serializes() -> None:
    preconditions = [PreconditionRef("pre-1", "equals", "goal-1", {"revision": 3})]
    requirements = [CapabilityRequirement("speech.output", "synthesize")]
    command = SystemCommand(
        "command-1",
        "decision-1",
        intent(),
        authority(),
        NOW,
        revisions(),
        deadline_at=NOW + timedelta(seconds=5),
        preconditions=preconditions,  # type: ignore[arg-type]
        required_capabilities=requirements,  # type: ignore[arg-type]
    )
    preconditions.clear()
    requirements.clear()

    data = command.to_dict()
    assert len(command.preconditions) == 1
    assert len(command.required_capabilities) == 1
    assert data["issued_at"] == NOW.isoformat()
    assert data["deadline_at"] == (NOW + timedelta(seconds=5)).isoformat()


@pytest.mark.parametrize("deadline", [NOW, NOW - timedelta(microseconds=1)])
def test_command_rejects_non_future_deadline(deadline: datetime) -> None:
    with pytest.raises(ValueError, match="later"):
        SystemCommand(
            "command-1", "decision-1", intent(), authority(), NOW, revisions(), deadline
        )


def test_command_orders_dst_fold_by_absolute_instant() -> None:
    zone = ZoneInfo("America/New_York")
    issued = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    later_same_wall_time = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)

    command = SystemCommand(
        "command-1",
        "decision-1",
        intent(),
        authority(),
        issued,
        revisions(),
        later_same_wall_time,
    )
    assert command.deadline_at is later_same_wall_time
