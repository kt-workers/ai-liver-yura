import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.domain.contracts import (
    AsyncWorkResult,
    AsyncWorkStatus,
    AuthorityRef,
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
    EventEnvelope,
    ExecutionResult,
    ExecutionStatus,
    ExecutiveDecision,
    IntentKind,
    IntentRef,
    PreconditionRef,
    RevisionVector,
    SystemCommand,
)

NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def test_every_public_contract_snapshot_is_strict_json_serializable() -> None:
    revisions = RevisionVector(1, goal_revision=2, attention_revision=3)
    authority = AuthorityRef("executive", "activity", "decision-1")
    intent = IntentRef(IntentKind.ACTIVITY, "intent-1")
    requirement = CapabilityRequirement("speech.output", "synthesize")
    precondition = PreconditionRef("pre-1", "equals", "goal-1", {"revision": 2})
    event = EventEnvelope("event-1", "input.received", "gateway", NOW, "trace-1", revisions, {})
    decision = ExecutiveDecision(
        "decision-1", (event.event_id,), (intent,), authority, revisions, NOW
    )
    command = SystemCommand(
        "command-1",
        decision.decision_id,
        intent,
        authority,
        NOW,
        revisions,
        NOW + timedelta(seconds=5),
        (precondition,),
        (requirement,),
    )
    capability = CapabilityDescriptor(
        "voice-1",
        "speech.output",
        ("synthesize",),
        CapabilityAvailability.AVAILABLE,
        1,
        {},
    )
    execution = ExecutionResult(
        command.command_id, ExecutionStatus.REQUESTED, NOW, revisions
    ).transition_to(ExecutionStatus.ACCEPTED, NOW)
    work = AsyncWorkResult(
        "request-1",
        AsyncWorkStatus.SUCCEEDED,
        revisions,
        NOW + timedelta(seconds=1),
        {"candidate": "ok"},
        NOW,
    )

    snapshots = [
        revisions.to_dict(),
        authority.to_dict(),
        intent.to_dict(),
        requirement.to_dict(),
        precondition.to_dict(),
        event.to_dict(),
        decision.to_dict(),
        command.to_dict(),
        capability.to_dict(),
        execution.to_dict(),
        work.to_dict(),
    ]
    for snapshot in snapshots:
        json.dumps(snapshot, allow_nan=False)


def test_domain_contracts_do_not_import_provider_or_framework_modules() -> None:
    forbidden_roots = {
        "anthropic",
        "fastapi",
        "google",
        "httpx",
        "live2d",
        "openai",
        "pygame",
        "requests",
        "voicevox",
    }
    contract_root = Path("app/domain/contracts")
    imported_roots: set[str] = set()
    for path in contract_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(forbidden_roots)
