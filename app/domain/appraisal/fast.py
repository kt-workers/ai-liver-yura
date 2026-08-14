from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.contracts import EventEnvelope

from .contracts import (
    AppraisalCandidate,
    AppraisalDimension,
    AppraisalPath,
    InternalStateSnapshot,
    StateDeltaProposal,
)


@dataclass(frozen=True, slots=True)
class DeterministicAppraisalRule:
    rule_id: str
    event_type: str
    dimensions: tuple[AppraisalDimension, ...]
    proposals: tuple[StateDeltaProposal, ...]
    salience: float
    relevance: float

    def __post_init__(self) -> None:
        from app.domain.contracts.common import require_identifier

        require_identifier(self.rule_id, "rule_id")
        require_identifier(self.event_type, "event_type")
        object.__setattr__(self, "dimensions", tuple(self.dimensions))
        object.__setattr__(self, "proposals", tuple(self.proposals))
        if type(self.salience) not in (int, float) or not 0 <= self.salience <= 1:
            raise ValueError("salience must be between 0 and 1")
        if type(self.relevance) not in (int, float) or not 0 <= self.relevance <= 1:
            raise ValueError("relevance must be between 0 and 1")


def appraise_event(
    event: EventEnvelope,
    snapshot: InternalStateSnapshot,
    rules: tuple[DeterministicAppraisalRule, ...],
    *,
    candidate_id: str,
    created_at: datetime,
) -> AppraisalCandidate | None:
    matches = [item for item in tuple(rules) if item.event_type == event.event_type]
    if len(matches) > 1:
        raise ValueError("deterministic appraisal event_type rules must be unique")
    if not matches:
        return None
    rule = matches[0]
    proposals = tuple(
        StateDeltaProposal(
            item.facet_ref,
            item.delta,
            item.confidence,
            (event.event_id, rule.rule_id),
        )
        for item in rule.proposals
    )
    return AppraisalCandidate(
        candidate_id,
        (event.event_id,),
        event.revisions.source_context_revision,
        snapshot.revision,
        AppraisalPath.FAST_DETERMINISTIC,
        rule.dimensions,
        proposals,
        rule.salience,
        rule.relevance,
        (rule.rule_id,),
        created_at,
    )
