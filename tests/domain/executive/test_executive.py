import asyncio
import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.appraisal import InternalStateSnapshot
from app.domain.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
    IntentKind,
    RevisionVector,
)
from app.domain.contracts.common import JsonValue
from app.domain.executive import (
    BodyIntentPayload,
    CommitmentTransitionIntent,
    CommitmentTransitionOperation,
    CommitmentTransitionPayload,
    ExecutiveContextSnapshot,
    ExecutiveDecisionAuthority,
    ExecutiveDecisionCandidate,
    ExecutiveDeliberator,
    ExecutiveFactKind,
    ExecutiveFactRef,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveInterruptibility,
    ExecutiveOutcome,
    ExecutivePolicy,
    ExecutivePreconditionRequirement,
    ExecutivePriority,
    GoalTransitionIntent,
    GoalTransitionOperation,
    GoalTransitionPayload,
    PreconditionFact,
    SpeechIntentPayload,
    build_request,
    commit_result,
    parse_candidate,
    to_foundation_decision,
    to_system_command,
)
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)

NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)
REVISIONS = RevisionVector(7, 5, 3)


def policy() -> ExecutivePolicy:
    return ExecutivePolicy(
        LLMExecutionPolicy(
            LLMModelClass.BALANCED,
            LLMReasoningEffort.MEDIUM,
            10,
            1,
            1000,
        )
    )


def snapshot(trigger_id: str = "trigger-1") -> ExecutiveContextSnapshot:
    return ExecutiveContextSnapshot(
        trigger_id,
        (f"event-{trigger_id}",),
        7,
        5,
        3,
        None,
        InternalStateSnapshot(2, 7, (), NOW),
        (
            ExecutiveFactRef("fact-desire", ExecutiveFactKind.GOAL, 5, {"strength": 0.8}),
            ExecutiveFactRef("goal-1", ExecutiveFactKind.GOAL, 5, {"active": True}),
            ExecutiveFactRef("goal-spec", ExecutiveFactKind.GOAL, 5, {"proposed": True}),
            ExecutiveFactRef("answer-user", ExecutiveFactKind.GOAL, 5, {"semantic": True}),
            ExecutiveFactRef("semantic-goal", ExecutiveFactKind.GOAL, 5, {"semantic": True}),
            ExecutiveFactRef("commitment-1", ExecutiveFactKind.COMMITMENT, 5, {"active": True}),
            ExecutiveFactRef(
                "commitment-spec",
                ExecutiveFactKind.COMMITMENT,
                5,
                {"proposed": True},
            ),
            ExecutiveFactRef(
                "unsupported-claim",
                ExecutiveFactKind.MEMORY_EVIDENCE,
                1,
                {"forbidden": True},
            ),
        ),
        (
            CapabilityDescriptor(
                "cap-speech",
                "speech",
                ("prepare",),
                CapabilityAvailability.AVAILABLE,
                2,
                {},
            ),
        ),
        (PreconditionFact("pre-turn", "turn", "equals", "available"),),
        NOW,
    )


def speech_intent() -> ExecutiveIntent:
    return ExecutiveIntent(
        "intent-speech",
        ExecutiveIntentKind.SPEECH,
        "応答を準備する",
        SpeechIntentPayload("answer-user"),
        ("fact-desire",),
        (CapabilityRequirement("speech", "prepare"),),
        (ExecutivePreconditionRequirement("pre-turn", "available"),),
        ("unsupported-claim",),
    )


def candidate(trigger_id: str = "trigger-1") -> ExecutiveDecisionCandidate:
    return ExecutiveDecisionCandidate(
        "candidate-1",
        trigger_id,
        (f"event-{trigger_id}",),
        7,
        5,
        3,
        ExecutiveOutcome.RESPOND,
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (speech_intent(),),
        (),
        (),
        ("fact-desire",),
        NOW,
    )


def candidate_json(trigger_id: str = "trigger-1") -> dict[str, object]:
    value = candidate(trigger_id).to_dict()
    value.pop("created_at")
    return value


def success(request: LLMRoleRequest, trigger_id: str = "trigger-1") -> LLMRoleResult:
    return LLMRoleResult(
        request.request_id,
        request.role_id,
        LLMRoleStatus.SUCCEEDED,
        request.revisions,
        NOW + timedelta(seconds=1),
        request.trace_id,
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(100, 50),
        StructuredPayload("executive.candidate.v1", cast(JsonValue, candidate_json(trigger_id))),
        started_at=NOW,
    )


def test_context_and_candidate_are_immutable_json_serializable_contracts() -> None:
    value = snapshot()
    source: dict[str, list[int]] = {"nested": [1, 2]}
    fact = ExecutiveFactRef("fact", ExecutiveFactKind.ENVIRONMENT, 1, cast(JsonValue, source))
    source["nested"].append(3)
    assert fact.to_dict()["payload"] == {"nested": [1, 2]}
    json.dumps(value.to_dict(), allow_nan=False)
    json.dumps(candidate().to_dict(), allow_nan=False)


@pytest.mark.parametrize(
    "outcome",
    [
        ExecutiveOutcome.WAIT,
        ExecutiveOutcome.IGNORE,
        ExecutiveOutcome.DEFER,
        ExecutiveOutcome.SILENCE,
    ],
)
def test_passive_outcomes_reject_executable_intents(outcome: ExecutiveOutcome) -> None:
    with pytest.raises(ValueError, match="passive"):
        replace(candidate(), outcome=outcome)


def test_outcome_requires_semantically_matching_intent_kind() -> None:
    body = ExecutiveIntent(
        "intent-body",
        ExecutiveIntentKind.BODY,
        "身体表現を準備する",
        BodyIntentPayload("answer-user"),
    )
    with pytest.raises(ValueError, match="speech"):
        replace(candidate(), intents=(body,))
    with pytest.raises(ValueError, match="activity or body"):
        replace(candidate(), outcome=ExecutiveOutcome.ACT)


@pytest.mark.parametrize(
    "payload",
    [
        {"final_utterance": "勝手な最終台詞", "execution_completed": True},
        {"joint_angles": [1, 2, 3]},
        123,
    ],
)
def test_intent_payload_rejects_nested_or_non_string_references(payload: object) -> None:
    with pytest.raises(ValueError):
        SpeechIntentPayload(cast(str, payload))


@pytest.mark.parametrize("operation", list(GoalTransitionOperation))
def test_goal_transition_operations_are_typed_and_do_not_mutate_store(
    operation: GoalTransitionOperation,
) -> None:
    kwargs = (
        {"goal_ref": None, "goal_spec_ref": "goal-spec"}
        if operation is GoalTransitionOperation.CREATE
        else {"goal_ref": "goal-1", "goal_spec_ref": None}
    )
    intent = GoalTransitionIntent(
        "goal-intent",
        operation,
        **kwargs,
        expected_goal_revision=5,
        payload=GoalTransitionPayload("semantic-goal", 50)
        if operation is GoalTransitionOperation.CREATE
        else GoalTransitionPayload(
            priority=50 if operation is GoalTransitionOperation.REPRIORITIZE else None,
            superseding_goal_ref="goal-1"
            if operation is GoalTransitionOperation.SUPERSEDE
            else None,
        ),
        reason_refs=("fact-desire",),
    )
    value = replace(
        candidate(),
        outcome=ExecutiveOutcome.CONTINUE_ACTIVITY,
        intents=(),
        goal_transition_intents=(intent,),
    )
    assert value.goal_transition_intents[0].operation is operation


@pytest.mark.parametrize("operation", list(CommitmentTransitionOperation))
def test_commitment_transition_operations_are_typed(
    operation: CommitmentTransitionOperation,
) -> None:
    kwargs = (
        {"commitment_ref": None, "commitment_spec_ref": "commitment-spec"}
        if operation is CommitmentTransitionOperation.CREATE
        else {"commitment_ref": "commitment-1", "commitment_spec_ref": None}
    )
    intent = CommitmentTransitionIntent(
        "commitment-intent",
        operation,
        **kwargs,
        expected_goal_revision=5,
        payload=CommitmentTransitionPayload("commitment-spec")
        if operation is CommitmentTransitionOperation.CREATE
        else CommitmentTransitionPayload(),
        reason_refs=("fact-desire",),
    )
    assert intent.operation is operation


def test_authority_commits_grounded_candidate_and_projects_foundation_contracts() -> None:
    authority = ExecutiveDecisionAuthority()
    committed = authority.commit(
        candidate(),
        snapshot(),
        current_revisions=REVISIONS,
        decision_id="decision-1",
        committed_at=NOW,
    )
    foundation = to_foundation_decision(committed)
    command = to_system_command(committed, committed.candidate.intents[0], command_id="command-1")
    assert foundation.authority.owner == "executive"
    assert foundation.intent_refs[0].kind is IntentKind.SPEECH
    assert command.required_capabilities[0].capability_type == "speech"
    assert command.preconditions[0].precondition_id == "pre-turn"
    assert command.preconditions[0].expected == "available"


def test_stale_context_goal_or_attention_revision_is_rejected() -> None:
    authority = ExecutiveDecisionAuthority()
    for revisions in (RevisionVector(8, 5, 3), RevisionVector(7, 6, 3), RevisionVector(7, 5, 4)):
        with pytest.raises(ValueError, match="stale"):
            authority.commit(
                candidate(),
                snapshot(),
                current_revisions=revisions,
                decision_id="decision",
                committed_at=NOW,
            )


def test_unknown_evidence_and_missing_capability_fail_closed() -> None:
    unknown = replace(candidate(), rationale_refs=("invented",))
    with pytest.raises(ValueError, match="bounded"):
        ExecutiveDecisionAuthority().commit(
            unknown, snapshot(), current_revisions=REVISIONS, decision_id="d1", committed_at=NOW
        )
    unavailable = replace(snapshot(), capabilities=())
    with pytest.raises(ValueError, match="capability"):
        ExecutiveDecisionAuthority().commit(
            candidate(),
            unavailable,
            current_revisions=REVISIONS,
            decision_id="d2",
            committed_at=NOW,
        )


def test_precondition_expectation_is_revalidated_at_commit() -> None:
    intent = replace(
        speech_intent(),
        preconditions=(ExecutivePreconditionRequirement("pre-turn", "busy"),),
    )
    proposed = replace(candidate(), intents=(intent,))
    with pytest.raises(ValueError, match="precondition"):
        ExecutiveDecisionAuthority().commit(
            proposed,
            snapshot(),
            current_revisions=REVISIONS,
            decision_id="decision-precondition",
            committed_at=NOW,
        )


def test_transition_and_forbidden_claim_refs_must_be_grounded() -> None:
    unknown_goal = GoalTransitionIntent(
        "goal-intent",
        GoalTransitionOperation.ABANDON,
        "unknown-goal",
        None,
        5,
        GoalTransitionPayload(),
        ("fact-desire",),
    )
    proposed = replace(
        candidate(),
        outcome=ExecutiveOutcome.CONTINUE_ACTIVITY,
        intents=(),
        goal_transition_intents=(unknown_goal,),
    )
    with pytest.raises(ValueError, match="goal transition"):
        ExecutiveDecisionAuthority().commit(
            proposed,
            snapshot(),
            current_revisions=REVISIONS,
            decision_id="decision-unknown-goal",
            committed_at=NOW,
        )
    ungrounded_payload = replace(
        speech_intent(), payload=SpeechIntentPayload("unknown-semantic-goal")
    )
    with pytest.raises(ValueError, match="bounded"):
        ExecutiveDecisionAuthority().commit(
            replace(candidate(), intents=(ungrounded_payload,)),
            snapshot(),
            current_revisions=REVISIONS,
            decision_id="decision-unknown-payload-ref",
            committed_at=NOW,
        )
    ungrounded_claim = replace(speech_intent(), forbidden_claim_refs=("unknown-claim",))
    with pytest.raises(ValueError, match="bounded"):
        ExecutiveDecisionAuthority().commit(
            replace(candidate(), intents=(ungrounded_claim,)),
            snapshot(),
            current_revisions=REVISIONS,
            decision_id="decision-unknown-claim",
            committed_at=NOW,
        )


def test_competing_decisions_for_same_trigger_commit_only_once_atomically() -> None:
    authority = ExecutiveDecisionAuthority()

    def attempt(index: int) -> str:
        try:
            authority.commit(
                candidate(),
                snapshot(),
                current_revisions=REVISIONS,
                decision_id=f"decision-{index}",
                committed_at=NOW,
            )
            return "committed"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, range(2)))
    assert outcomes.count("committed") == 1
    assert outcomes.count("rejected") == 1


def test_strict_parser_rejects_unknown_schema_fields_and_raw_enum_values() -> None:
    raw = candidate_json()
    raw["raw_text"] = "再解釈してはいけない"
    with pytest.raises(ValueError, match="schema"):
        parse_candidate(raw, snapshot(), created_at=NOW)
    raw = candidate_json()
    raw["outcome"] = "invented"
    with pytest.raises(ValueError, match="invalid"):
        parse_candidate(raw, snapshot(), created_at=NOW)


def test_role_commit_revalidates_exact_snapshot_and_exchange() -> None:
    context = snapshot()
    request = build_request(
        context, request_id="request-1", trace_id="trace-1", created_at=NOW, policy=policy()
    )
    committed = commit_result(
        request,
        success(request),
        snapshot=context,
        current_revisions=REVISIONS,
        authority=ExecutiveDecisionAuthority(),
        decision_id="decision-1",
        policy=policy(),
    )
    assert committed.candidate.outcome is ExecutiveOutcome.RESPOND
    with pytest.raises(ValueError, match="snapshot"):
        commit_result(
            request,
            success(request),
            snapshot=replace(
                context,
                facts=context.facts + (ExecutiveFactRef("late", ExecutiveFactKind.TIME, 1, {}),),
            ),
            current_revisions=REVISIONS,
            authority=ExecutiveDecisionAuthority(),
            decision_id="decision-2",
            policy=policy(),
        )


@pytest.mark.asyncio
async def test_slow_background_role_does_not_block_foreground_decision() -> None:
    background_started = asyncio.Event()
    release_background = asyncio.Event()

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            request_value = cast(Mapping[str, JsonValue], request.input.value)
            trigger_id = cast(str, request_value["trigger_id"])
            if trigger_id == "background":
                background_started.set()
                await release_background.wait()
            return success(request, trigger_id)

    deliberator = ExecutiveDeliberator(Port(), policy(), ExecutiveDecisionAuthority())
    background = asyncio.create_task(
        deliberator.deliberate(
            snapshot("background"),
            request_id="request-bg",
            trace_id="trace-bg",
            decision_id="decision-bg",
            created_at=NOW,
            current_revisions=REVISIONS,
        )
    )
    await background_started.wait()
    foreground = await asyncio.wait_for(
        deliberator.deliberate(
            snapshot("foreground"),
            request_id="request-fg",
            trace_id="trace-fg",
            decision_id="decision-fg",
            created_at=NOW,
            current_revisions=REVISIONS,
        ),
        timeout=0.2,
    )
    assert foreground.candidate.trigger_id == "foreground"
    release_background.set()
    await background
