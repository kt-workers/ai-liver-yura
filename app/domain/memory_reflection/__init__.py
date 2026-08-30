"""#364 Reflectionの候補生成・support観測・closed acceptance境界。"""

from .authority import ReflectionCandidateAuthority
from .contracts import (
    MemoryCandidateProposal,
    ReflectionAcceptancePolicy,
    ReflectionCandidateResult,
    ReflectionCandidateStatus,
    ReflectionContextSnapshot,
    ReflectionEventKind,
    ReflectionRelationHint,
    ReflectionRunResult,
    ReflectionRunTelemetry,
    ReflectionSourceEvidence,
    ReflectionSourceKind,
    ReflectionSupportObservation,
    ReflectionSupportRelation,
    ReflectionTrigger,
    ReflectionTriggerKind,
)
from .runtime import ReflectionCoordinator, ReflectionProposalPort, ReflectionSupportPort

__all__ = [
    "MemoryCandidateProposal",
    "ReflectionAcceptancePolicy",
    "ReflectionCandidateAuthority",
    "ReflectionCandidateResult",
    "ReflectionCandidateStatus",
    "ReflectionContextSnapshot",
    "ReflectionCoordinator",
    "ReflectionEventKind",
    "ReflectionProposalPort",
    "ReflectionRelationHint",
    "ReflectionRunResult",
    "ReflectionRunTelemetry",
    "ReflectionSourceEvidence",
    "ReflectionSourceKind",
    "ReflectionSupportObservation",
    "ReflectionSupportPort",
    "ReflectionSupportRelation",
    "ReflectionTrigger",
    "ReflectionTriggerKind",
]
