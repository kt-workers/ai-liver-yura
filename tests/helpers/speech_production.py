"""Speech production試験で実Ownerを明示構築する。"""

from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.composition.speech_semantics_sources import (
    ProductionSpeechSources,
)
from app.domain.activity_execution.authority import ActivityExecutionAuthority
from app.domain.contracts.finalization import AuthorityReadPublication
from app.domain.contracts.semantic_subject import RuntimeSubjectIdentity
from app.domain.goals import (
    CommitmentState,
    CommitmentStatus,
    GoalCommitmentSnapshot,
    GoalKind,
    GoalState,
    GoalStatus,
    InterruptionPolicy,
)
from app.domain.goals.store import GoalCommitmentStore
from app.domain.memory import MemoryStoreAuthority
from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry
from app.infrastructure.persistence import PersistenceOperationResult
from tests.domain.executive.test_executive import NOW
from tests.domain.memory.test_memory_store_retrieval import authority
from tests.helpers.goal_semantics import semantic_spec

IDENTITY = RuntimeSubjectIdentity("runtime-test", "runtime-test", 1, 1)


def production_sources() -> ProductionSpeechSources:
    goal = GoalState(
        "goal-1",
        GoalKind.SOCIAL,
        "semantic",
        None,
        "test-decision",
        GoalStatus.ACTIVE,
        50,
        (),
        (),
        (),
        (),
        InterruptionPolicy.PROTECTED,
        NOW,
        NOW,
        5,
        semantic_goal_spec=semantic_spec("semantic"),
    )
    commitment = CommitmentState(
        "commitment-1",
        "test-promised-action",
        None,
        ("event-1",),
        "source-decision",
        (),
        CommitmentStatus.ACTIVE,
        50,
        50,
        (),
        (),
        NOW,
        NOW,
        5,
        semantic_commitment_spec=semantic_spec("test-promised-action"),
    )
    goals = GoalCommitmentStore(GoalCommitmentSnapshot(5, (goal,), (commitment,), NOW))
    memory, _ = authority()
    return ProductionSpeechSources(
        goals=goals,
        memory=InMemorySpeechMemory(memory),
        execution=ActivityExecutionAuthority(),
    )


class InMemorySpeechMemory(CoreMemoryPersistenceBinding):
    """unit試験でだけMemory public非同期境界をメモリ内Ownerへ接続する。"""

    def __init__(self, owner: MemoryStoreAuthority) -> None:
        self.owner = owner

    async def read_semantic_assertion_publication(
        self, memory_id: str, expected_revision: int | None = None
    ) -> PersistenceOperationResult[AuthorityReadPublication[MemorySemanticAssertionEntry]]:
        return PersistenceOperationResult(
            self.owner.read_semantic_assertion_publication(memory_id, expected_revision)
        )


def memory_owner(sources: ProductionSpeechSources) -> MemoryStoreAuthority:
    memory = sources._memory
    assert isinstance(memory, InMemorySpeechMemory)
    return memory.owner
