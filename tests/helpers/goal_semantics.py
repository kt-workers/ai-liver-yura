"""試験専用の明示意味仕様。productionの意味方針ではない。"""

from app.domain.goal_commitment_semantics import (
    GoalCommitmentSemanticPolarity,
    GoalCommitmentSemanticSpec,
    GoalCommitmentSemanticSubjectKind,
)


def semantic_spec(ref: str) -> GoalCommitmentSemanticSpec:
    return GoalCommitmentSemanticSpec(
        ref,
        1,
        GoalCommitmentSemanticSubjectKind.SELF,
        None,
        "test-intended-content",
        {"test": True},
        GoalCommitmentSemanticPolarity.AFFIRM,
        None,
    )
