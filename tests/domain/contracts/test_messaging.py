import json
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.contracts import (
    AuthorityRef,
    CapabilityRequirement,
    EventEnvelope,
    ExecutiveDecision,
    IntentKind,
    IntentRef,
    JsonInput,
    PreconditionRef,
    RevisionVector,
    SystemCommand,
)

NOW = datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)
REVISIONS = RevisionVector(source_context_revision=8, goal_revision=2, attention_revision=5)
AUTHORITY = AuthorityRef(owner="executive", scope="conscious_goal_action_selection")


def test_event_envelope_preserves_trace_and_serializable_payload() -> None:
    segments = ["a", "b"]
    payload: dict[str, JsonInput] = {"text": "こんにちは", "segments": segments}
    event = EventEnvelope(
        event_id="event-1",
        event_type="user.message.received",
        source="input.console",
        occurred_at=NOW,
        trace_id="trace-1",
        correlation_id="conversation-1",
        revisions=REVISIONS,
        payload=payload,
    )

    segments.append("mutated-after-create")

    serialized = event.to_dict()
    assert serialized["payload"] == {"text": "こんにちは", "segments": ["a", "b"]}
    assert serialized["revisions"] == REVISIONS.to_dict()
    json.dumps(serialized, ensure_ascii=False)


def test_event_envelope_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EventEnvelope(
            event_id="event-1",
            event_type="test",
            source="test",
            occurred_at=datetime(2026, 8, 13),
            trace_id="trace-1",
            revisions=REVISIONS,
        )


def test_executive_decision_transports_intent_refs_without_realizer_payload() -> None:
    decision = ExecutiveDecision(
        decision_id="decision-1",
        created_at=NOW,
        authority=AUTHORITY,
        source_event_ids=("event-1",),
        intent_refs=(
            IntentRef("speech-1", IntentKind.SPEECH),
            IntentRef("body-1", IntentKind.BODY),
            IntentRef("goal-transition-1", IntentKind.GOAL_TRANSITION),
        ),
        revisions=REVISIONS,
    )

    intent_refs = cast(list[dict[str, str]], decision.to_dict()["intent_refs"])
    assert [item["kind"] for item in intent_refs] == [
        "speech",
        "body",
        "goal_transition",
    ]
    json.dumps(decision.to_dict())


def test_system_command_carries_preconditions_capabilities_and_deadline() -> None:
    command = SystemCommand(
        command_id="command-1",
        decision_id="decision-1",
        intent_ref=IntentRef("body-1", IntentKind.BODY),
        authority=AUTHORITY,
        issued_at=NOW,
        deadline_at=NOW + timedelta(seconds=2),
        revisions=REVISIONS,
        preconditions=(
            PreconditionRef(
                precondition_id="pc-goal-revision",
                predicate="revision_matches",
                subject_ref="goal:g-1",
                expected=2,
            ),
        ),
        required_capabilities=(
            CapabilityRequirement(capability_type="body.motion", operation="execute"),
        ),
    )

    serialized = command.to_dict()
    assert serialized["intent_ref"] == {"intent_id": "body-1", "kind": "body"}
    requirements = cast(list[dict[str, object]], serialized["required_capabilities"])
    assert requirements[0]["capability_type"] == "body.motion"
    json.dumps(serialized)


def test_system_command_rejects_expired_or_equal_deadline() -> None:
    with pytest.raises(ValueError, match="later than issued_at"):
        SystemCommand(
            command_id="command-1",
            decision_id="decision-1",
            intent_ref=IntentRef("speech-1", IntentKind.SPEECH),
            authority=AUTHORITY,
            issued_at=NOW,
            deadline_at=NOW,
            revisions=REVISIONS,
        )
