from datetime import datetime, timedelta, timezone

import pytest

from app.domain.contracts import RevisionVector
from app.runtime.kernel import (
    BoundedWorkQueue,
    QueueAdmissionStatus,
    QueuePolicy,
    RuntimeWorkItem,
    WorkPriority,
)

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def item(
    work_id: str,
    priority: WorkPriority = WorkPriority.NORMAL,
    *,
    key: str | None = None,
    seconds: int = 0,
    payload: int = 1,
) -> RuntimeWorkItem[int]:
    return RuntimeWorkItem(
        work_id,
        "lane",
        payload,
        priority,
        RevisionVector(1),
        NOW + timedelta(seconds=seconds),
        key,
    )


def test_reject_new_is_bounded_and_explicit() -> None:
    queue = BoundedWorkQueue[int](1, QueuePolicy.REJECT_NEW)
    assert queue.put(item("one")).status is QueueAdmissionStatus.ACCEPTED
    assert queue.put(item("two")).status is QueueAdmissionStatus.REJECTED
    assert [value.work_id for value in queue.items()] == ["one"]


def test_drop_oldest_reports_displaced_work() -> None:
    queue = BoundedWorkQueue[int](2, QueuePolicy.DROP_OLDEST)
    queue.put(item("old", seconds=0))
    queue.put(item("newer", seconds=1))
    result = queue.put(item("newest", seconds=2))
    assert result.status is QueueAdmissionStatus.DROPPED_OLDEST
    assert result.displaced_work_ids == ("old",)


@pytest.mark.parametrize("policy", [QueuePolicy.LATEST_WINS, QueuePolicy.REPLACE_SAME_KEY])
def test_key_replacement_owns_latest_item(policy: QueuePolicy) -> None:
    queue = BoundedWorkQueue[int](2, policy)
    queue.put(item("old", key="same"))
    result = queue.put(item("new", key="same"))
    assert result.status is QueueAdmissionStatus.REPLACED
    assert result.displaced_work_ids == ("old",)
    assert [value.work_id for value in queue.items()] == ["new"]


def test_latest_wins_rejects_missing_key() -> None:
    queue = BoundedWorkQueue[int](2, QueuePolicy.LATEST_WINS)
    assert queue.put(item("one")).status is QueueAdmissionStatus.REJECTED


def test_coalesce_uses_module_function_and_reports_both_inputs() -> None:
    def combine(old: RuntimeWorkItem[int], new: RuntimeWorkItem[int]) -> RuntimeWorkItem[int]:
        return item("combined", key=old.queue_key, payload=old.payload + new.payload)

    queue = BoundedWorkQueue[int](2, QueuePolicy.COALESCE, coalescer=combine)
    queue.put(item("one", key="comments", payload=2))
    result = queue.put(item("two", key="comments", payload=3))
    assert result.status is QueueAdmissionStatus.COALESCED
    assert result.displaced_work_ids == ("one", "two")
    assert queue.items()[0].payload == 5


def test_duplicate_work_identity_is_rejected_without_queue_mutation() -> None:
    queue = BoundedWorkQueue[int](2, QueuePolicy.REJECT_NEW)
    queue.put(item("same", payload=1))
    result = queue.put(item("same", payload=2))
    assert result.status is QueueAdmissionStatus.REJECTED
    assert [value.payload for value in queue.items()] == [1]


def test_priority_fifo_and_bounded_anti_starvation() -> None:
    queue = BoundedWorkQueue[int](8, QueuePolicy.REJECT_NEW, max_priority_burst=2)
    queue.put(item("background", WorkPriority.BACKGROUND))
    for index in range(4):
        queue.put(item(f"foreground-{index}", WorkPriority.FOREGROUND))
    assert [queue.get().work_id for _ in range(3)] == [  # type: ignore[union-attr]
        "foreground-0",
        "foreground-1",
        "background",
    ]


def test_oldest_lower_priority_progresses_when_intermediate_priority_is_busy() -> None:
    queue = BoundedWorkQueue[int](10, QueuePolicy.REJECT_NEW, max_priority_burst=2)
    queue.put(item("background-oldest", WorkPriority.BACKGROUND, seconds=0))
    queue.put(item("normal", WorkPriority.NORMAL, seconds=1))
    for index in range(4):
        queue.put(item(f"foreground-{index}", WorkPriority.FOREGROUND, seconds=2 + index))
    assert [queue.get().work_id for _ in range(3)] == [  # type: ignore[union-attr]
        "foreground-0",
        "foreground-1",
        "background-oldest",
    ]


def test_critical_priority_can_override_fairness() -> None:
    queue = BoundedWorkQueue[int](5, QueuePolicy.REJECT_NEW, max_priority_burst=1)
    queue.put(item("normal", WorkPriority.NORMAL))
    queue.put(item("critical-1", WorkPriority.CRITICAL))
    queue.put(item("critical-2", WorkPriority.CRITICAL))
    assert queue.get().work_id == "critical-1"  # type: ignore[union-attr]
    assert queue.get().work_id == "critical-2"  # type: ignore[union-attr]


def test_work_item_uses_absolute_deadline_ordering() -> None:
    with pytest.raises(ValueError, match="later"):
        RuntimeWorkItem(
            "one", "lane", 1, WorkPriority.NORMAL, RevisionVector(1), NOW, deadline_at=NOW
        )
