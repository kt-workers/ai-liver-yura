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
from .postgresql_connection import PostgresConnectionPolicy, PostgresDatabase, PostgresEndpoint
from .postgresql_memory import PostgresMemoryRepository
from .postgresql_snapshots import PostgresLifecycleSnapshotRepository
from .runtime import PersistenceOperationResult, PostgresPersistenceRuntime
from .snapshots import (
    InMemoryLifecycleSnapshotRepository,
    LifecycleSnapshotRepositoryPort,
    SqliteLifecycleSnapshotRepository,
)
from .sqlite_memory import SqliteMemoryRepository
from .worker import (
    SnapshotPersistenceRequest,
    SnapshotPersistenceRetryPolicy,
    SnapshotPersistenceWorker,
)

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
    "PostgresConnectionPolicy",
    "PostgresDatabase",
    "PostgresEndpoint",
    "PostgresMemoryRepository",
    "PostgresLifecycleSnapshotRepository",
    "PostgresPersistenceRuntime",
    "PersistenceOperationResult",
    "SnapshotPersistenceRequest",
    "SnapshotPersistenceRetryPolicy",
    "SnapshotPersistenceWorker",
    "SqliteLifecycleSnapshotRepository",
    "SqliteMemoryRepository",
]
