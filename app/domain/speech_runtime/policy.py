from __future__ import annotations

from dataclasses import dataclass

from app.domain.contracts.common import require_identifier, require_revision


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} は1以上の整数でなければなりません")
    return value


@dataclass(frozen=True, slots=True)
class SpeechRuntimeOperationalPolicy:
    policy_id: str
    policy_revision: int
    queue_max_candidates: int
    queue_max_consecutive_foreground: int
    prepared_candidate_ttl_ms: int
    revalidation_max_age_ms: int
    repair_max_generation_attempts: int
    repair_evidence_max_refs: int
    speculative_tts_parallelism_per_candidate: int

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        for field_name in (
            "queue_max_candidates",
            "queue_max_consecutive_foreground",
            "prepared_candidate_ttl_ms",
            "revalidation_max_age_ms",
            "repair_max_generation_attempts",
            "repair_evidence_max_refs",
            "speculative_tts_parallelism_per_candidate",
        ):
            _positive_int(getattr(self, field_name), field_name)
        if self.prepared_candidate_ttl_ms <= self.revalidation_max_age_ms:
            raise ValueError(
                "prepared_candidate_ttl_ms は revalidation_max_age_ms より大きくなければなりません"
            )
        if self.repair_max_generation_attempts != 1:
            raise ValueError("v1 repair_max_generation_attempts は1固定です")
        if self.speculative_tts_parallelism_per_candidate != 1:
            raise ValueError("v1 speculative_tts_parallelism_per_candidate は1固定です")

    def same_generation(self, other: SpeechRuntimeOperationalPolicy) -> bool:
        return (
            isinstance(other, SpeechRuntimeOperationalPolicy)
            and self.policy_id == other.policy_id
            and self.policy_revision == other.policy_revision
        )


V2_SPEECH_RUNTIME_OPERATIONAL_POLICY = SpeechRuntimeOperationalPolicy(
    policy_id="v2.speech-runtime-operational.default",
    policy_revision=1,
    queue_max_candidates=8,
    queue_max_consecutive_foreground=3,
    prepared_candidate_ttl_ms=15000,
    revalidation_max_age_ms=3000,
    repair_max_generation_attempts=1,
    repair_evidence_max_refs=64,
    speculative_tts_parallelism_per_candidate=1,
)
