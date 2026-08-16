from datetime import datetime, timedelta, timezone

from app.domain.attention import (
    AttentionCoordinator,
    AttentionIngressOperation,
    AttentionIngressSignal,
    AttentionPriority,
    AttentionProjectableFact,
    AttentionSourceKind,
    AttentionTurnStore,
    ExecutiveTriggerEligibility,
    SpeechCandidateSchedulingFact,
    SpeechCandidateSchedulingPhase,
    SpeechSchedulingOperation,
    SpeechSchedulingView,
    UserInteractionAttentionProjector,
    scheduling_directives_for_trigger,
)

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def test_user_projector_and_coordinator_enqueue_without_executive_completion() -> None:
    store = AttentionTurnStore()
    enqueued: list[ExecutiveTriggerEligibility] = []
    coordinator = AttentionCoordinator(store, store, enqueued.append)
    signal = UserInteractionAttentionProjector().project(AttentionProjectableFact("user-1", 1, NOW))

    trigger = coordinator.handle(signal, 3, NOW)

    assert trigger is not None
    assert trigger.source_ref == "user-1"
    assert trigger.priority is AttentionPriority.DIRECT_USER
    assert enqueued == [trigger]


def test_speech_boundary_emits_directives_without_mutating_view() -> None:
    store = AttentionTurnStore()
    store.offer(
        UserInteractionAttentionProjector().project(AttentionProjectableFact("user-1", 1, NOW))
    )
    trigger = store.claim_next(3, NOW)
    assert trigger is not None
    presenting = SpeechCandidateSchedulingFact(
        "speech-a",
        SpeechCandidateSchedulingPhase.PRESENTING,
        AttentionPriority.BACKGROUND,
        True,
        1,
    )
    queued = SpeechCandidateSchedulingFact(
        "speech-b",
        SpeechCandidateSchedulingPhase.QUEUED,
        AttentionPriority.BACKGROUND,
        False,
        1,
    )
    view = SpeechSchedulingView(7, presenting, (queued,))

    directives = scheduling_directives_for_trigger(view, trigger, NOW + timedelta(seconds=1))

    assert {directive.operation for directive in directives} == {
        SpeechSchedulingOperation.REQUEST_INTERRUPT,
        SpeechSchedulingOperation.SUPERSEDE_QUEUED,
    }
    assert view.presenting_candidate == presenting
    assert view.queued_candidates == (queued,)
    assert all(directive.expected_speech_revision == 7 for directive in directives)


def test_non_user_source_cannot_spoof_direct_user() -> None:
    store = AttentionTurnStore()
    spoofed = AttentionIngressSignal(
        "signal-1",
        AttentionIngressOperation.OFFER,
        "stream-1",
        AttentionSourceKind.STREAMING,
        1,
        NOW,
        requested_priority=AttentionPriority.DIRECT_USER,
        trusted_direct_user=True,
    )

    try:
        store.offer(spoofed)
    except ValueError as error:
        assert "priority" in str(error)
    else:
        raise AssertionError("DIRECT_USER偽装を受理してはいけません")
