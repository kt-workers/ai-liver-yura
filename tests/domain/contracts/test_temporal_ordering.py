from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.contracts import (
    AsyncResultStatus,
    AsyncWorkResult,
    AuthorityRef,
    ExecutionResult,
    ExecutionStatus,
    IntentKind,
    IntentRef,
    RevisionVector,
    SystemCommand,
)

ZONE = ZoneInfo("America/New_York")
REVISIONS = RevisionVector(source_context_revision=5, goal_revision=3)
AUTHORITY = AuthorityRef(owner="executive", scope="conscious_goal_action_selection")


def _fall_back_earlier() -> datetime:
    return datetime(2026, 11, 1, 1, 45, tzinfo=ZONE, fold=0)


def _fall_back_later() -> datetime:
    return datetime(2026, 11, 1, 1, 15, tzinfo=ZONE, fold=1)


def test_system_command_accepts_absolute_later_deadline_across_dst_fold() -> None:
    command = SystemCommand(
        command_id="command-dst-fold",
        decision_id="decision-dst-fold",
        intent_ref=IntentRef("speech-dst-fold", IntentKind.SPEECH),
        authority=AUTHORITY,
        issued_at=_fall_back_earlier(),
        deadline_at=_fall_back_later(),
        revisions=REVISIONS,
    )

    assert command.deadline_at == _fall_back_later()


def test_system_command_rejects_absolute_expired_deadline_across_dst_fold() -> None:
    with pytest.raises(ValueError, match="later than issued_at"):
        SystemCommand(
            command_id="command-expired-dst-fold",
            decision_id="decision-dst-fold",
            intent_ref=IntentRef("speech-expired-dst-fold", IntentKind.SPEECH),
            authority=AUTHORITY,
            issued_at=_fall_back_later(),
            deadline_at=_fall_back_earlier(),
            revisions=REVISIONS,
        )


def test_execution_transition_accepts_absolute_forward_dst_fold() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-dst-fold",
        command_id="command-dst-fold",
        occurred_at=_fall_back_earlier(),
        revisions=REVISIONS,
    )

    accepted = requested.transition_to(
        ExecutionStatus.ACCEPTED,
        occurred_at=_fall_back_later(),
    )

    assert accepted.occurred_at == _fall_back_later()


def test_execution_transition_rejects_absolute_backwards_dst_fold() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-backwards-dst-fold",
        command_id="command-dst-fold",
        occurred_at=_fall_back_later(),
        revisions=REVISIONS,
    )

    with pytest.raises(ValueError, match="must not move backwards"):
        requested.transition_to(
            ExecutionStatus.ACCEPTED,
            occurred_at=_fall_back_earlier(),
        )


def test_async_result_accepts_absolute_forward_dst_fold() -> None:
    result = AsyncWorkResult(
        request_id="request-dst-fold",
        status=AsyncResultStatus.SUCCEEDED,
        started_at=_fall_back_earlier(),
        completed_at=_fall_back_later(),
        revisions=REVISIONS,
    )

    assert result.completed_at == _fall_back_later()


def test_async_result_rejects_absolute_backwards_dst_fold() -> None:
    with pytest.raises(ValueError, match="must not be later than completed_at"):
        AsyncWorkResult(
            request_id="request-backwards-dst-fold",
            status=AsyncResultStatus.FAILED,
            started_at=_fall_back_later(),
            completed_at=_fall_back_earlier(),
            revisions=REVISIONS,
        )
