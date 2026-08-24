from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain.contracts.common import require_aware, require_identifier, require_revision
from app.domain.llm import LLMInterruptibility, LLMPriority


class SpeechReadinessState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"
    CANCELLED = "cancelled"


class VerifierReadinessState(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"
    STALE = "stale"
    CANCELLED = "cancelled"


class AudioReadinessState(str, Enum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"
    DISCARDED = "discarded"
    CANCELLED = "cancelled"


class CandidateLifecycle(str, Enum):
    PREPARING = "preparing"
    PREPARED = "prepared"
    QUEUED = "queued"
    REVALIDATING = "revalidating"
    READY_TO_PRESENT = "ready_to_present"
    PRESENTING = "presenting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    STALE = "stale"
    REJECTED = "rejected"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class SemanticVerificationRequirement(str, Enum):
    REQUIRED = "required"
    NOT_REQUIRED_BY_CLOSED_POLICY = "not_required_by_closed_policy"


class SpeechPresentationMode(str, Enum):
    AUDIO_WITH_TEXT = "audio_with_text"
    TEXT_ONLY = "text_only"
    FAIL_CLOSED = "fail_closed"


class SpeechPresentationReportStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED_BEFORE_START = "failed_before_start"
    FAILED_AFTER_START = "failed_after_start"


class TTSPreparationMode(str, Enum):
    AFTER_SEMANTIC_ACCEPTANCE = "after_semantic_acceptance"
    SPECULATIVE_AFTER_PERFORMANCE = "speculative_after_performance"
    DISABLED = "disabled"


class SemanticRepairDisposition(str, Enum):
    ACCEPTED = "accepted"
    REPAIR_ONCE = "repair_once"
    REJECTED_FINAL = "rejected_final"
    VERIFIER_FAILED = "verifier_failed"
    REPLAN_REQUIRED = "replan_required"


@dataclass(frozen=True, slots=True)
class SpeechComponentReadiness:
    semantics: SpeechReadinessState
    character: SpeechReadinessState
    verifier: VerifierReadinessState
    performance: SpeechReadinessState
    audio: AudioReadinessState

    def __post_init__(self) -> None:
        if not isinstance(self.semantics, SpeechReadinessState):
            raise ValueError("semantics readiness が不正です")
        if not isinstance(self.character, SpeechReadinessState):
            raise ValueError("character readiness が不正です")
        if not isinstance(self.verifier, VerifierReadinessState):
            raise ValueError("verifier readiness が不正です")
        if not isinstance(self.performance, SpeechReadinessState):
            raise ValueError("performance readiness が不正です")
        if not isinstance(self.audio, AudioReadinessState):
            raise ValueError("audio readiness が不正です")


@dataclass(frozen=True, slots=True)
class SpeechPreparationRequest:
    preparation_id: str
    source_decision_id: str
    speech_intent_ref: str
    source_event_ids: tuple[str, ...]
    source_context_revision: int
    goal_revision: int | None
    attention_revision: int | None
    priority: LLMPriority
    interruptibility: LLMInterruptibility
    required_preconditions: tuple[str, ...]
    expiry_policy_ref: str
    semantic_verification_requirement: SemanticVerificationRequirement
    semantic_verification_policy_ref: str
    presentation_policy_ref: str
    created_at: datetime
    trace_id: str
    semantic_skip_proof: SemanticVerificationSkipProof | None = None

    def __post_init__(self) -> None:
        for name in (
            "preparation_id",
            "source_decision_id",
            "speech_intent_ref",
            "expiry_policy_ref",
            "semantic_verification_policy_ref",
            "presentation_policy_ref",
            "trace_id",
        ):
            require_identifier(getattr(self, name), name)
        events = tuple(self.source_event_ids)
        if not events or any(not isinstance(item, str) or not item.strip() for item in events):
            raise ValueError("source_event_ids が不正です")
        if len(events) != len(set(events)):
            raise ValueError("source_event_ids は一意です")
        object.__setattr__(self, "source_event_ids", events)
        require_revision(self.source_context_revision, "source_context_revision")
        require_revision(self.goal_revision, "goal_revision", optional=True)
        require_revision(self.attention_revision, "attention_revision", optional=True)
        if not isinstance(self.priority, LLMPriority) or not isinstance(
            self.interruptibility, LLMInterruptibility
        ):
            raise ValueError("priority/interruptibility が不正です")
        if not isinstance(self.semantic_verification_requirement, SemanticVerificationRequirement):
            raise ValueError("semantic verification requirement が不正です")
        if (
            self.semantic_verification_requirement
            is (SemanticVerificationRequirement.NOT_REQUIRED_BY_CLOSED_POLICY)
            and self.semantic_skip_proof is None
        ):
            raise ValueError("verifier skipにはclosed policy proofが必要です")
        if self.semantic_verification_requirement is SemanticVerificationRequirement.REQUIRED:
            if self.semantic_skip_proof is not None:
                raise ValueError("REQUIRED verifierにskip proofは指定できません")
        if self.semantic_skip_proof is not None and not isinstance(
            self.semantic_skip_proof, SemanticVerificationSkipProof
        ):
            raise ValueError("semantic_skip_proof が不正です")
        preconditions = tuple(self.required_preconditions)
        if any(not isinstance(item, str) or not item.strip() for item in preconditions):
            raise ValueError("required_preconditions が不正です")
        if len(preconditions) != len(set(preconditions)):
            raise ValueError("required_preconditions は一意です")
        object.__setattr__(self, "required_preconditions", preconditions)
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class SemanticVerificationSkipProof:
    policy_id: str
    policy_revision: int
    reason_code: str
    closed_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("policy_id", "reason_code"):
            require_identifier(getattr(self, name), name)
        require_revision(self.policy_revision, "policy_revision")
        conditions = tuple(self.closed_conditions)
        if not conditions or any(
            not isinstance(item, str) or not item.strip() for item in conditions
        ):
            raise ValueError("closed_conditions が不正です")
        object.__setattr__(self, "closed_conditions", conditions)


@dataclass(frozen=True, slots=True)
class SemanticRepairAttempt:
    attempt: int
    maximum_attempts: int
    speech_plan_id: str
    utterance_id: str
    rejection_categories: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    prior_realizations: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.attempt) is not int
            or type(self.maximum_attempts) is not int
            or not 0 <= self.attempt <= self.maximum_attempts
        ):
            raise ValueError("repair attempt が不正です")
        for name in ("speech_plan_id", "utterance_id"):
            require_identifier(getattr(self, name), name)
        for name in ("rejection_categories", "evidence_refs", "prior_realizations"):
            values = tuple(getattr(self, name))
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{name} が不正です")
            object.__setattr__(self, name, values)
        if self.attempt == 1 and self.prior_realizations:
            raise ValueError("repair prior_realizationsは空です")


@dataclass(frozen=True, slots=True)
class SpeechPresentationCapabilityView:
    capability_id: str
    revision: int
    output_available: bool
    audio_available: bool
    text_available: bool
    timing_publication_available: bool

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, "capability_id")
        require_revision(self.revision, "revision")
        if any(
            type(value) is not bool
            for value in (
                self.output_available,
                self.audio_available,
                self.text_available,
                self.timing_publication_available,
            )
        ):
            raise ValueError("presentation capability が不正です")


@dataclass(frozen=True, slots=True)
class PreparedSpeechCandidate:
    candidate_id: str
    preparation_id: str
    source_decision_id: str
    source_event_ids: tuple[str, ...]
    speech_plan_id: str
    utterance_id: str | None
    performance_plan_id: str | None
    source_context_revision: int
    goal_revision: int | None
    attention_revision: int | None
    priority: LLMPriority
    interruptibility: LLMInterruptibility
    expiry_policy_ref: str
    required_preconditions: tuple[str, ...]
    semantic_requirement: SemanticVerificationRequirement
    semantic_acceptance_id: str | None
    prepared_audio_ref: str | None
    presentation_modes: tuple[SpeechPresentationMode, ...]
    readiness: SpeechComponentReadiness
    lifecycle: CandidateLifecycle
    created_at: datetime
    updated_at: datetime
    expression_revision: int | None = None
    performance_generation: int = 1
    repair_count: int = 0
    turn_id: str | None = None
    focus_revision: int | None = None
    semantic_skip_proof: SemanticVerificationSkipProof | None = None
    response_obligation_id: str | None = None
    expires_at: datetime | None = None
    character_definition_revision: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "preparation_id",
            "source_decision_id",
            "speech_plan_id",
            "expiry_policy_ref",
        ):
            require_identifier(getattr(self, name), name)
        events = tuple(self.source_event_ids)
        if not events or any(not isinstance(item, str) or not item.strip() for item in events):
            raise ValueError("source_event_ids が不正です")
        object.__setattr__(self, "source_event_ids", events)
        for name in ("source_context_revision", "goal_revision", "attention_revision"):
            require_revision(getattr(self, name), name, optional=name != "source_context_revision")
        if not isinstance(self.readiness, SpeechComponentReadiness) or not isinstance(
            self.lifecycle, CandidateLifecycle
        ):
            raise ValueError("candidate state が不正です")
        modes = tuple(self.presentation_modes)
        if not modes or any(not isinstance(item, SpeechPresentationMode) for item in modes):
            raise ValueError("presentation_modes が不正です")
        object.__setattr__(self, "presentation_modes", modes)
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        require_revision(self.expression_revision, "expression_revision", optional=True)
        if type(self.performance_generation) is not int or self.performance_generation < 1:
            raise ValueError("performance_generation が不正です")
        if type(self.repair_count) is not int or not 0 <= self.repair_count <= 1:
            raise ValueError("repair_count が不正です")
        if self.turn_id is not None:
            require_identifier(self.turn_id, "turn_id")
        require_revision(self.focus_revision, "focus_revision", optional=True)
        if (
            self.semantic_requirement
            is SemanticVerificationRequirement.NOT_REQUIRED_BY_CLOSED_POLICY
        ):
            if self.semantic_skip_proof is None:
                raise ValueError("verifier skipにはclosed policy proofが必要です")
        elif self.semantic_skip_proof is not None:
            raise ValueError("REQUIRED verifierにskip proofは指定できません")
        if self.semantic_skip_proof is not None and not isinstance(
            self.semantic_skip_proof, SemanticVerificationSkipProof
        ):
            raise ValueError("semantic_skip_proof が不正です")
        if self.response_obligation_id is not None:
            require_identifier(self.response_obligation_id, "response_obligation_id")
        if self.expires_at is not None:
            require_aware(self.expires_at, "expires_at")
        require_revision(
            self.character_definition_revision,
            "character_definition_revision",
            optional=True,
        )


@dataclass(frozen=True, slots=True)
class SpeechPresentationCommitState:
    source_context_revision: int
    goal_revision: int | None
    attention_revision: int | None
    turn_id: str
    response_obligation_id: str | None
    satisfied_preconditions: tuple[str, ...]
    capability: SpeechPresentationCapabilityView
    expression_revision: int | None
    observed_at: datetime
    focus_revision: int | None = None
    semantic_acceptance_id: str | None = None
    performance_plan_id: str | None = None
    prepared_audio_ref: str | None = None
    character_definition_revision: int | None = None
    character_compatible: bool = True
    expiry_valid: bool = True

    def __post_init__(self) -> None:
        require_revision(self.source_context_revision, "source_context_revision")
        require_revision(self.goal_revision, "goal_revision", optional=True)
        require_revision(self.attention_revision, "attention_revision", optional=True)
        require_revision(self.expression_revision, "expression_revision", optional=True)
        require_revision(self.focus_revision, "focus_revision", optional=True)
        require_revision(
            self.character_definition_revision,
            "character_definition_revision",
            optional=True,
        )
        if type(self.character_compatible) is not bool or type(self.expiry_valid) is not bool:
            raise ValueError("live compatibility/expiry が不正です")
        require_identifier(self.turn_id, "turn_id")
        if self.response_obligation_id is not None:
            require_identifier(self.response_obligation_id, "response_obligation_id")
        if not isinstance(self.capability, SpeechPresentationCapabilityView):
            raise ValueError("capability が不正です")
        for name in (
            "semantic_acceptance_id",
            "performance_plan_id",
            "prepared_audio_ref",
        ):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class SpeechPresentationCommand:
    presentation_id: str
    candidate_id: str
    utterance_id: str
    audio_ref: str | None
    modes: tuple[SpeechPresentationMode, ...]
    committed_at: datetime

    def __post_init__(self) -> None:
        for name in ("presentation_id", "candidate_id", "utterance_id"):
            require_identifier(getattr(self, name), name)
        if self.audio_ref is not None:
            require_identifier(self.audio_ref, "audio_ref")
        require_aware(self.committed_at, "committed_at")


@dataclass(frozen=True, slots=True)
class SpeechPresentationReport:
    presentation_id: str
    candidate_id: str
    status: SpeechPresentationReportStatus
    output_modes: tuple[SpeechPresentationMode, ...]
    started_at: datetime | None
    completed_at: datetime | None
    audio_ref: str | None
    timing_ref: str | None
    failure_code: str | None = None
    interruption_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("presentation_id", "candidate_id"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.status, SpeechPresentationReportStatus):
            raise ValueError("report status が不正です")
        modes = tuple(self.output_modes)
        if not modes or any(not isinstance(item, SpeechPresentationMode) for item in modes):
            raise ValueError("output_modes が不正です")
        object.__setattr__(self, "output_modes", modes)
        if self.started_at is not None:
            require_aware(self.started_at, "started_at")
        if self.completed_at is not None:
            require_aware(self.completed_at, "completed_at")
        if (
            self.status
            in (
                SpeechPresentationReportStatus.COMPLETED,
                SpeechPresentationReportStatus.FAILED_AFTER_START,
                SpeechPresentationReportStatus.INTERRUPTED,
            )
            and self.started_at is None
        ):
            raise ValueError("started後のreportにはstarted_atが必要です")
