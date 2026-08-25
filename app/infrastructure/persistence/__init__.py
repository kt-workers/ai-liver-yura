"""#359 Persistence adapterの公開境界。"""

from .contracts import (
    DurabilityReceipt,
    DurabilityStatus,
    IntegrityStatus,
    PersistenceAvailability,
    PersistenceError,
    PersistenceFailureCode,
    PersistenceSnapshotEnvelope,
    RehydrationCandidate,
)
from .snapshots import (
    InMemoryLifecycleSnapshotRepository,
    LifecycleSnapshotRepositoryPort,
    SqliteLifecycleSnapshotRepository,
)
from .sqlite_memory import SqliteMemoryRepository
from .worker import SnapshotPersistenceRequest, SnapshotPersistenceWorker

__all__ = [
    "DurabilityReceipt",
    "DurabilityStatus",
    "InMemoryLifecycleSnapshotRepository",
    "IntegrityStatus",
    "LifecycleSnapshotRepositoryPort",
    "PersistenceAvailability",
    "PersistenceError",
    "PersistenceFailureCode",
    "PersistenceSnapshotEnvelope",
    "RehydrationCandidate",
    "SnapshotPersistenceRequest",
    "SnapshotPersistenceWorker",
    "SqliteLifecycleSnapshotRepository",
    "SqliteMemoryRepository",
]
