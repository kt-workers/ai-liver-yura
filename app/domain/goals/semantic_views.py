"""current Goal / Commitmentの内容を元Ownerの状態から公開する。"""

from dataclasses import dataclass

from app.domain.goal_commitment_semantics import (
    GoalCommitmentSemanticCertainty,
    GoalCommitmentSemanticModality,
    GoalCommitmentSemanticSpec,
)

from .contracts import CommitmentState, CommitmentStatus, GoalState, GoalStatus


@dataclass(frozen=True, slots=True)
class GoalCommitmentSemanticView:
    state: GoalState | CommitmentState

    def __post_init__(self) -> None:
        if type(self.state) not in (GoalState, CommitmentState):
            raise ValueError("GoalまたはCommitmentのcurrent typed stateが必要です")

    @property
    def state_kind(self) -> GoalCommitmentSemanticModality:
        return self.modality

    @property
    def modality(self) -> GoalCommitmentSemanticModality:
        return (
            GoalCommitmentSemanticModality.GOAL
            if isinstance(self.state, GoalState)
            else GoalCommitmentSemanticModality.COMMITMENT
        )

    @property
    def certainty(self) -> GoalCommitmentSemanticCertainty:
        return GoalCommitmentSemanticCertainty.CERTAIN

    @property
    def state_id(self) -> str:
        return self.state.goal_id if isinstance(self.state, GoalState) else self.state.commitment_id

    @property
    def state_revision(self) -> int:
        return self.state.revision

    @property
    def semantic_spec(self) -> GoalCommitmentSemanticSpec:
        return (
            self.state.semantic_goal_spec
            if isinstance(self.state, GoalState)
            else self.state.semantic_commitment_spec
        )

    @property
    def semantic_ref(self) -> str:
        return self.semantic_spec.semantic_ref

    @property
    def semantic_revision(self) -> int:
        return self.semantic_spec.semantic_revision

    @property
    def lifecycle_status(self) -> GoalStatus | CommitmentStatus:
        return self.state.status

    @property
    def source_decision_id(self) -> str:
        return (
            self.state.created_from_decision_id
            if isinstance(self.state, GoalState)
            else self.state.source_decision_id
        )

    @property
    def reason_refs(self) -> tuple[str, ...]:
        return (
            self.state.motivation_refs
            if isinstance(self.state, GoalState)
            else self.state.reason_refs
        )

    @property
    def source_event_ids(self) -> tuple[str, ...]:
        return () if isinstance(self.state, GoalState) else self.state.source_event_ids

    @property
    def created_from_decision_id(self) -> str | None:
        return self.state.created_from_decision_id if isinstance(self.state, GoalState) else None

    @property
    def motivation_refs(self) -> tuple[str, ...]:
        return self.state.motivation_refs if isinstance(self.state, GoalState) else ()
