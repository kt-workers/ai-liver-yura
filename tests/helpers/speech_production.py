"""Speech production試験で実Ownerを明示構築する。"""

from app.composition.speech_semantics_sources import (
    ProductionSpeechSources,
    SpeechOwnerSourceRegistration,
)
from app.domain.activity_execution.authority import ActivityExecutionAuthority
from app.domain.contracts.semantic_subject import RuntimeSubjectIdentity
from app.domain.executive.contracts import ExecutiveFactKind
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
from app.domain.speech_semantics_vocabulary import SpeechSourceContractKind as K
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
        memory=memory,
        execution=ActivityExecutionAuthority(),
        registrations=(
            SpeechOwnerSourceRegistration("goal-1", ExecutiveFactKind.GOAL, "goal-1", K.GOAL),
            SpeechOwnerSourceRegistration(
                "commitment-1", ExecutiveFactKind.COMMITMENT, "commitment-1", K.COMMITMENT
            ),
        ),
    )
