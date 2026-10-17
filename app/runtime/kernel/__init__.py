"""外部接続に依存しない本体の有界実行カーネル。"""

from .cancellation import CancellationRegistry, CancellationToken
from .clock import RuntimeClock
from .contracts import (
    CancellationRecord,
    CoordinatorState,
    LaneDiagnostics,
    LaneErrorPolicy,
    QueueAdmission,
    QueueAdmissionStatus,
    QueuePolicy,
    RuntimeDiagnosticsSnapshot,
    RuntimeHealth,
    RuntimeLanePolicy,
    RuntimeSchedulerPolicy,
    RuntimeWorkItem,
    WorkDisposition,
    WorkOutcome,
    WorkPriority,
)
from .coordinator import RuntimeCoordinator
from .queue import BoundedWorkQueue

__all__ = [
    "BoundedWorkQueue",
    "CancellationRecord",
    "CancellationRegistry",
    "CancellationToken",
    "CoordinatorState",
    "LaneDiagnostics",
    "LaneErrorPolicy",
    "QueueAdmission",
    "QueueAdmissionStatus",
    "QueuePolicy",
    "RuntimeClock",
    "RuntimeCoordinator",
    "RuntimeDiagnosticsSnapshot",
    "RuntimeHealth",
    "RuntimeLanePolicy",
    "RuntimeSchedulerPolicy",
    "RuntimeWorkItem",
    "WorkDisposition",
    "WorkOutcome",
    "WorkPriority",
]
