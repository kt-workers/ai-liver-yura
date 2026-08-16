from datetime import datetime, timedelta, timezone

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityExecutionRecord,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionPreflightSnapshot,
)
from app.domain.appraisal import AppraisalCandidate, AppraisalPath
from app.domain.attention import (
    AttentionCoordinator,
    AttentionPriority,
    AttentionTurnStore,
    ExecutiveTriggerEligibility,
    SpeechCandidateSchedulingFact,
    SpeechCandidateSchedulingPhase,
    SpeechSchedulingOperation,
    SpeechSchedulingView,
    scheduling_directives_for_trigger,
)
from app.domain.contracts import (
    AuthorityRef,
    CapabilityAvailability,
    EventEnvelope,
    ExecutionStatus,
    IntentKind,
    IntentRef,
    RevisionVector,
    SystemCommand,
)
from app.domain.goals import AutonomyTrigger, AutonomyTriggerKind
from app.domain.input_gateway import (
    InputAdmission,
    InputAdmissionStatus,
    InputModality,
    InputPermission,
    InputSourceState,
    NormalizedInputEvent,
)
from app.usecases.attention import (
    ActivityAttentionProjector,
    AppraisalAttentionProjector,
    CommitmentAttentionProjector,
    GoalAttentionProjector,
    GoalCommitmentAttentionFact,
    UserInteractionAttentionProjector,
)

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def accepted_user_admission() -> InputAdmission:
    return InputAdmission(
        InputAdmissionStatus.ACCEPTED,
        NormalizedInputEvent(
            EventEnvelope(
                "event-user", "input.text", "input_gateway", NOW, "trace-1", RevisionVector(1), {}
            ),
            InputModality.TEXT,
            InputSourceState(
                "source-user", "user", CapabilityAvailability.AVAILABLE, InputPermission.GRANTED
            ),
        ),
    )


def appraisal_candidate() -> AppraisalCandidate:
    return AppraisalCandidate(
        "appraisal-1",
        ("event-1",),
        2,
        3,
        AppraisalPath.FAST_DETERMINISTIC,
        (),
        (),
        0.7,
        0.8,
        (),
        NOW,
    )


def actual_execution_record() -> tuple[ActivityInvocation, ActivityExecutionRecord]:
    command = SystemCommand(
        "command-1",
        "decision-1",
        IntentRef(IntentKind.ACTIVITY, "intent-1"),
        AuthorityRef("executive", "conscious_goal_action", "decision-1"),
        NOW,
        RevisionVector(5),
    )
    invocation = ActivityInvocation(
        "invocation-1", command, "activity.run", {}, ActivityInterruptibility.INTERRUPTIBLE, NOW
    )
    authority = ActivityExecutionAuthority()
    preflight = ExecutionPreflightSnapshot(RevisionVector(5), (), (), NOW)
    authority.admit(invocation, preflight)
    authority.start("command-1", preflight, NOW + timedelta(seconds=1), "dispatch-1")
    return invocation, authority.apply_report(
        ExecutionAdapterReport(
            "command-1",
            "invocation-1",
            "dispatch-1",
            ExecutionStatus.COMPLETED,
            NOW + timedelta(seconds=2),
            {},
        )
    )


def test_user_projector_requires_accepted_input_gateway_provenance() -> None:
    projector = UserInteractionAttentionProjector()
    with pytest.raises(ValueError):
        projector.project(object())  # type: ignore[arg-type]
    signal = projector.project(accepted_user_admission())
    assert signal.source_ref == "event-user"
    assert signal.trusted_direct_user is True


def test_typed_appraisal_and_goal_commitment_facts_are_projected() -> None:
    assert AppraisalAttentionProjector().project(appraisal_candidate()).source_ref == "appraisal-1"
    goal = GoalCommitmentAttentionFact(
        AutonomyTrigger("goal-1", AutonomyTriggerKind.ACTIVE_GOAL, "goal-1", 4, 80), 4, NOW
    )
    commitment = GoalCommitmentAttentionFact(
        AutonomyTrigger(
            "commitment-1", AutonomyTriggerKind.COMMITMENT_DUE_CHECK, "commitment-1", 4, 80
        ),
        4,
        NOW,
    )
    assert GoalAttentionProjector().project(goal).source_ref == "goal-1"
    assert CommitmentAttentionProjector().project(commitment).source_ref == "commitment-1"
    with pytest.raises(ValueError):
        GoalAttentionProjector().project(commitment)


def test_activity_projector_rejects_intent_and_accepts_actual_execution_fact() -> None:
    invocation, record = actual_execution_record()
    projector = ActivityAttentionProjector()
    with pytest.raises(ValueError):
        projector.project(invocation)  # type: ignore[arg-type]
    assert projector.project(record).source_ref == "command-1"


def test_user_projector_and_coordinator_enqueue_without_executive_completion() -> None:
    store = AttentionTurnStore()
    enqueued: list[ExecutiveTriggerEligibility] = []
    trigger = AttentionCoordinator(store, store, enqueued.append).handle(
        UserInteractionAttentionProjector().project(accepted_user_admission()), 3, NOW
    )
    assert trigger is not None and trigger.priority is AttentionPriority.DIRECT_USER
    assert enqueued == [trigger]


def test_speech_boundary_emits_directives_without_mutating_view() -> None:
    store = AttentionTurnStore()
    store.offer(UserInteractionAttentionProjector().project(accepted_user_admission()))
    trigger = store.claim_next(3, NOW)
    assert trigger is not None
    presenting = SpeechCandidateSchedulingFact(
        "speech-a", SpeechCandidateSchedulingPhase.PRESENTING, AttentionPriority.BACKGROUND, True, 1
    )
    queued = SpeechCandidateSchedulingFact(
        "speech-b", SpeechCandidateSchedulingPhase.QUEUED, AttentionPriority.BACKGROUND, False, 1
    )
    view = SpeechSchedulingView(7, presenting, (queued,))
    directives = scheduling_directives_for_trigger(view, trigger, NOW + timedelta(seconds=1))
    assert {item.operation for item in directives} == {
        SpeechSchedulingOperation.REQUEST_INTERRUPT,
        SpeechSchedulingOperation.SUPERSEDE_QUEUED,
    }
    assert view.presenting_candidate == presenting and view.queued_candidates == (queued,)
