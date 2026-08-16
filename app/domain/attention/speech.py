from __future__ import annotations

from datetime import datetime

from .contracts import (
    ExecutiveTriggerEligibility,
    SpeechCandidateSchedulingFact,
    SpeechSchedulingDirective,
    SpeechSchedulingOperation,
    SpeechSchedulingView,
)


def scheduling_directives_for_trigger(
    view: SpeechSchedulingView,
    trigger: ExecutiveTriggerEligibility,
    occurred_at: datetime,
) -> tuple[SpeechSchedulingDirective, ...]:
    """Attention判断を#348へ再検証可能なdirectiveとして渡す。"""
    if not isinstance(view, SpeechSchedulingView) or not isinstance(
        trigger, ExecutiveTriggerEligibility
    ):
        raise ValueError("speech scheduling viewとexecutive triggerが必要です")
    directives: list[SpeechSchedulingDirective] = []
    for candidate in view.queued_candidates:
        if candidate.priority < trigger.priority:
            directives.append(
                _directive(
                    view,
                    trigger,
                    candidate,
                    SpeechSchedulingOperation.SUPERSEDE_QUEUED,
                    occurred_at,
                )
            )
    presenting = view.presenting_candidate
    if (
        presenting is not None
        and presenting.interruptible
        and presenting.priority < trigger.priority
        and trigger.interruption_allowed
    ):
        directives.append(
            _directive(
                view,
                trigger,
                presenting,
                SpeechSchedulingOperation.REQUEST_INTERRUPT,
                occurred_at,
            )
        )
    return tuple(directives)


def _directive(
    view: SpeechSchedulingView,
    trigger: ExecutiveTriggerEligibility,
    candidate: SpeechCandidateSchedulingFact,
    operation: SpeechSchedulingOperation,
    occurred_at: datetime,
) -> SpeechSchedulingDirective:
    return SpeechSchedulingDirective(
        f"speech-{view.speech_revision}-{trigger.trigger_id}-{candidate.candidate_ref}-{operation.value}",
        operation,
        candidate.candidate_ref,
        trigger.trigger_id,
        view.speech_revision,
        trigger.attention_revision,
        trigger.reason_kind,
        occurred_at,
    )
