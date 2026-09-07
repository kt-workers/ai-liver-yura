from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from app.domain.contracts.common import require_identifier, require_revision
from app.domain.llm import LLMPriority


class SpeechCandidatePriority(str, Enum):
    BACKGROUND = "background"
    NORMAL = "normal"
    FOREGROUND = "foreground"
    DIRECT_USER = "direct_user"

    @property
    def rank(self) -> int:
        return {
            SpeechCandidatePriority.BACKGROUND: 0,
            SpeechCandidatePriority.NORMAL: 1,
            SpeechCandidatePriority.FOREGROUND: 2,
            SpeechCandidatePriority.DIRECT_USER: 3,
        }[self]

    @property
    def llm_priority(self) -> LLMPriority:
        return {
            SpeechCandidatePriority.BACKGROUND: LLMPriority.BACKGROUND,
            SpeechCandidatePriority.NORMAL: LLMPriority.NORMAL,
            SpeechCandidatePriority.FOREGROUND: LLMPriority.FOREGROUND,
            SpeechCandidatePriority.DIRECT_USER: LLMPriority.FOREGROUND,
        }[self]


class SpeechQueueOverflowPolicy(str, Enum):
    REJECT_NEW = "reject_new"
    EVICT_LOWEST_PRIORITY_OLDEST = "evict_lowest_priority_oldest"


@dataclass(frozen=True, slots=True)
class SpeechExpiryRule:
    priority: SpeechCandidatePriority
    max_candidate_age_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.priority, SpeechCandidatePriority):
            raise ValueError("expiry priority が不正です")
        value = self.max_candidate_age_seconds
        if type(value) not in (int, float) or not isfinite(value) or value <= 0:
            raise ValueError("max_candidate_age_seconds は有限の正数でなければなりません")
        object.__setattr__(self, "max_candidate_age_seconds", float(value))


@dataclass(frozen=True, slots=True)
class SpeechRuntimeOperationalPolicy:
    policy_id: str
    policy_revision: int
    prepared_queue_capacity: int
    max_in_flight_preparations: int
    max_background_in_flight_preparations: int
    max_regeneration_attempts: int
    expiry_rules: tuple[SpeechExpiryRule, ...]
    speculative_tts_limit: int
    queue_overflow_policy: SpeechQueueOverflowPolicy

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        self._require_int_at_least(self.prepared_queue_capacity, 1, "prepared_queue_capacity")
        self._require_int_at_least(
            self.max_in_flight_preparations,
            1,
            "max_in_flight_preparations",
        )
        self._require_int_at_least(
            self.max_background_in_flight_preparations,
            0,
            "max_background_in_flight_preparations",
        )
        self._require_int_at_least(
            self.max_regeneration_attempts,
            0,
            "max_regeneration_attempts",
        )
        self._require_int_at_least(self.speculative_tts_limit, 0, "speculative_tts_limit")
        if self.max_background_in_flight_preparations > self.max_in_flight_preparations:
            raise ValueError("background in-flight上限はtotal上限を超えられません")
        if not isinstance(self.queue_overflow_policy, SpeechQueueOverflowPolicy):
            raise ValueError("queue_overflow_policy が不正です")
        rules = tuple(self.expiry_rules)
        if any(not isinstance(rule, SpeechExpiryRule) for rule in rules):
            raise ValueError("expiry_rules が不正です")
        priorities = tuple(rule.priority for rule in rules)
        if len(priorities) != len(set(priorities)):
            raise ValueError("expiry_rules priority は一意でなければなりません")
        if set(priorities) != set(SpeechCandidatePriority):
            raise ValueError("expiry_rules は全Speech priorityをexactly once覆う必要があります")
        object.__setattr__(self, "expiry_rules", rules)

    def expiry_rule_for(self, priority: SpeechCandidatePriority) -> SpeechExpiryRule:
        if not isinstance(priority, SpeechCandidatePriority):
            raise ValueError("priority が不正です")
        return next(rule for rule in self.expiry_rules if rule.priority is priority)

    def same_generation(self, policy_id: str, policy_revision: int) -> bool:
        return self.policy_id == policy_id and self.policy_revision == policy_revision

    @staticmethod
    def _require_int_at_least(value: object, minimum: int, field_name: str) -> None:
        if type(value) is not int or value < minimum:
            raise ValueError(f"{field_name} は{minimum}以上の整数でなければなりません")
