from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum

from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
    timestamp_to_json,
)


class AttentionSourceKind(str, Enum):
    USER_INTERACTION = "user_interaction"
    GOAL = "goal"
    COMMITMENT = "commitment"
    ACTIVITY = "activity"
    APPRAISAL = "appraisal"
    STREAMING = "streaming"
    GAME = "game"
    REFLECTION = "reflection"
    AUTONOMOUS = "autonomous"


class AttentionPriority(IntEnum):
    BACKGROUND = 0
    NORMAL = 1
    FOREGROUND = 2
    DIRECT_USER = 3


class AttentionIngressOperation(str, Enum):
    OFFER = "offer"
    REFRESH = "refresh"
    RESOLVE = "resolve"


class AttentionTransitionOperation(str, Enum):
    ACQUIRE_FOREGROUND = "acquire_foreground"
    RELEASE_FOREGROUND = "release_foreground"
    ADD_MONITOR = "add_monitor"
    REMOVE_MONITOR = "remove_monitor"
    ASSIGN_TURN = "assign_turn"
    RELEASE_TURN = "release_turn"
    SET_RESPONSE_OBLIGATION = "set_response_obligation"
    CLEAR_RESPONSE_OBLIGATION = "clear_response_obligation"


class SpeechCandidateSchedulingPhase(str, Enum):
    PREPARING = "preparing"
    PREPARED = "prepared"
    QUEUED = "queued"
    REVALIDATING = "revalidating"
    READY_TO_PRESENT = "ready_to_present"
    PRESENTING = "presenting"


class SpeechSchedulingOperation(str, Enum):
    REVALIDATE = "revalidate"
    SUPERSEDE_QUEUED = "supersede_queued"
    REQUEST_SOFT_FINISH = "request_soft_finish"
    REQUEST_INTERRUPT = "request_interrupt"


def _id_or_none(value: str | None, name: str) -> None:
    if value is not None:
        require_identifier(value, name)


def _positive(value: object, name: str, *, zero: bool = False) -> int:
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError(f"{name} は{'0以上' if zero else '正の'}整数でなければなりません")
    return value


def _ids(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{name} は配列でなければなりません")
    result = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in result) or len(result) != len(
        set(result)
    ):
        raise ValueError(f"{name} は一意な識別子の配列でなければなりません")
    return result


@dataclass(frozen=True, slots=True)
class AttentionPriorityRule:
    kind: AttentionSourceKind
    default_priority: AttentionPriority
    maximum_priority: AttentionPriority

    def __post_init__(self) -> None:
        if (
            not isinstance(self.kind, AttentionSourceKind)
            or not isinstance(self.default_priority, AttentionPriority)
            or not isinstance(self.maximum_priority, AttentionPriority)
        ):
            raise ValueError("priority ruleが不正です")
        if self.default_priority > self.maximum_priority:
            raise ValueError("default priorityはmaximum priorityを超えられません")
        if (
            self.maximum_priority is AttentionPriority.DIRECT_USER
            and self.kind is not AttentionSourceKind.USER_INTERACTION
        ):
            raise ValueError("DIRECT_USER は user interaction だけに許可されます")


@dataclass(frozen=True, slots=True)
class InterruptionThreshold:
    current_foreground_priority: AttentionPriority | None
    minimum_challenger_priority: AttentionPriority

    def __post_init__(self) -> None:
        if self.current_foreground_priority is not None and not isinstance(
            self.current_foreground_priority, AttentionPriority
        ):
            raise ValueError("current foreground priorityが不正です")
        if not isinstance(self.minimum_challenger_priority, AttentionPriority):
            raise ValueError("minimum challenger priorityが不正です")


@dataclass(frozen=True, slots=True)
class AttentionSchedulingPolicy:
    policy_id: str
    policy_revision: int
    attention_budget: int
    source_kind_budgets: tuple[tuple[AttentionSourceKind, int], ...]
    source_priority_rules: tuple[AttentionPriorityRule, ...]
    interruption_thresholds: tuple[InterruptionThreshold, ...]
    max_same_source_burst: int
    max_priority_burst: int
    cooldown_claims: int

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        for name in (
            "attention_budget",
            "max_same_source_burst",
            "max_priority_burst",
            "cooldown_claims",
        ):
            _positive(getattr(self, name), name)
        budgets = tuple(self.source_kind_budgets)
        if (
            len(budgets) != len(AttentionSourceKind)
            or any(
                not isinstance(kind, AttentionSourceKind) or type(limit) is not int or limit < 1
                for kind, limit in budgets
            )
            or len({kind for kind, _ in budgets}) != len(budgets)
        ):
            raise ValueError("source kind budgetは全kindを一度ずつ持たなければなりません")
        rules = tuple(self.source_priority_rules)
        if (
            len(rules) != len(AttentionSourceKind)
            or any(not isinstance(rule, AttentionPriorityRule) for rule in rules)
            or len({rule.kind for rule in rules}) != len(rules)
        ):
            raise ValueError("source priority ruleは全kindを一度ずつ持たなければなりません")
        thresholds = tuple(self.interruption_thresholds)
        if (
            len(thresholds) != len(AttentionPriority) + 1
            or any(not isinstance(item, InterruptionThreshold) for item in thresholds)
            or len({item.current_foreground_priority for item in thresholds}) != len(thresholds)
        ):
            raise ValueError(
                "interruption thresholdはnoneと全priorityを一度ずつ持たなければなりません"
            )
        object.__setattr__(
            self, "source_kind_budgets", tuple(sorted(budgets, key=lambda item: item[0].value))
        )
        object.__setattr__(
            self, "source_priority_rules", tuple(sorted(rules, key=lambda item: item.kind.value))
        )
        object.__setattr__(self, "interruption_thresholds", thresholds)

    @classmethod
    def production(cls) -> AttentionSchedulingPolicy:
        values = {
            AttentionSourceKind.USER_INTERACTION: (
                4,
                AttentionPriority.DIRECT_USER,
                AttentionPriority.DIRECT_USER,
            ),
            AttentionSourceKind.GOAL: (2, AttentionPriority.NORMAL, AttentionPriority.FOREGROUND),
            AttentionSourceKind.COMMITMENT: (
                2,
                AttentionPriority.NORMAL,
                AttentionPriority.FOREGROUND,
            ),
            AttentionSourceKind.ACTIVITY: (
                2,
                AttentionPriority.NORMAL,
                AttentionPriority.FOREGROUND,
            ),
            AttentionSourceKind.APPRAISAL: (
                2,
                AttentionPriority.NORMAL,
                AttentionPriority.FOREGROUND,
            ),
            AttentionSourceKind.STREAMING: (
                2,
                AttentionPriority.BACKGROUND,
                AttentionPriority.FOREGROUND,
            ),
            AttentionSourceKind.GAME: (2, AttentionPriority.NORMAL, AttentionPriority.FOREGROUND),
            AttentionSourceKind.REFLECTION: (
                1,
                AttentionPriority.BACKGROUND,
                AttentionPriority.BACKGROUND,
            ),
            AttentionSourceKind.AUTONOMOUS: (
                1,
                AttentionPriority.BACKGROUND,
                AttentionPriority.BACKGROUND,
            ),
        }
        return cls(
            "attention-scheduling-production",
            1,
            8,
            tuple((kind, value[0]) for kind, value in values.items()),
            tuple(
                AttentionPriorityRule(kind, value[1], value[2]) for kind, value in values.items()
            ),
            (
                InterruptionThreshold(None, AttentionPriority.BACKGROUND),
                InterruptionThreshold(AttentionPriority.BACKGROUND, AttentionPriority.NORMAL),
                InterruptionThreshold(AttentionPriority.NORMAL, AttentionPriority.FOREGROUND),
                InterruptionThreshold(AttentionPriority.FOREGROUND, AttentionPriority.DIRECT_USER),
                InterruptionThreshold(AttentionPriority.DIRECT_USER, AttentionPriority.DIRECT_USER),
            ),
            2,
            4,
            1,
        )

    def budget_for(self, kind: AttentionSourceKind) -> int:
        return dict(self.source_kind_budgets)[kind]

    def priority_rule_for(self, kind: AttentionSourceKind) -> AttentionPriorityRule:
        return next(rule for rule in self.source_priority_rules if rule.kind is kind)

    def interruption_minimum_for(self, priority: AttentionPriority | None) -> AttentionPriority:
        return next(
            item.minimum_challenger_priority
            for item in self.interruption_thresholds
            if item.current_foreground_priority is priority
        )


@dataclass(frozen=True, slots=True)
class AttentionIngressSignal:
    signal_id: str
    operation: AttentionIngressOperation
    source_ref: str
    source_kind: AttentionSourceKind
    source_context_revision: int
    occurred_at: datetime
    source_revision: int | None = None
    requested_priority: AttentionPriority | None = None
    expires_at: datetime | None = None
    trusted_direct_user: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.signal_id, "signal_id")
        require_identifier(self.source_ref, "source_ref")
        if not isinstance(self.operation, AttentionIngressOperation) or not isinstance(
            self.source_kind, AttentionSourceKind
        ):
            raise ValueError("ingress signalのoperation又はsource kindが不正です")
        require_revision(self.source_context_revision, "source_context_revision")
        if self.source_revision is not None:
            require_revision(self.source_revision, "source_revision")
        if self.requested_priority is not None and not isinstance(
            self.requested_priority, AttentionPriority
        ):
            raise ValueError("requested_priorityが不正です")
        if type(self.trusted_direct_user) is not bool:
            raise ValueError("trusted_direct_userはboolでなければなりません")
        require_aware(self.occurred_at, "occurred_at")
        if self.expires_at is not None:
            require_aware(self.expires_at, "expires_at")
            if self.expires_at <= self.occurred_at:
                raise ValueError("expires_atはoccurred_atより後でなければなりません")
        if self.operation is AttentionIngressOperation.RESOLVE and (
            self.requested_priority is not None or self.expires_at is not None
        ):
            raise ValueError("resolve signalはpriority又はexpiryを持てません")


@dataclass(frozen=True, slots=True)
class AttentionSource:
    source_ref: str
    kind: AttentionSourceKind
    effective_priority: AttentionPriority
    source_context_revision: int
    occurred_at: datetime
    last_refreshed_at: datetime
    source_revision: int | None = None
    expires_at: datetime | None = None
    coalesced_count: int = 1

    def __post_init__(self) -> None:
        require_identifier(self.source_ref, "source_ref")
        if not isinstance(self.kind, AttentionSourceKind) or not isinstance(
            self.effective_priority, AttentionPriority
        ):
            raise ValueError("source kind又はeffective priorityが不正です")
        require_revision(self.source_context_revision, "source_context_revision")
        if self.source_revision is not None:
            require_revision(self.source_revision, "source_revision")
        require_aware(self.occurred_at, "occurred_at")
        require_aware(self.last_refreshed_at, "last_refreshed_at")
        if self.last_refreshed_at < self.occurred_at:
            raise ValueError("last_refreshed_atはoccurred_atより前にできません")
        if self.expires_at is not None:
            require_aware(self.expires_at, "expires_at")
            if self.expires_at <= self.occurred_at:
                raise ValueError("expires_atはoccurred_atより後でなければなりません")
        _positive(self.coalesced_count, "coalesced_count")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_ref": self.source_ref,
            "kind": self.kind.value,
            "effective_priority": self.effective_priority.name.lower(),
            "source_context_revision": self.source_context_revision,
            "source_revision": self.source_revision,
            "occurred_at": timestamp_to_json(self.occurred_at),
            "last_refreshed_at": timestamp_to_json(self.last_refreshed_at),
            "expires_at": None if self.expires_at is None else timestamp_to_json(self.expires_at),
            "coalesced_count": self.coalesced_count,
        }


@dataclass(frozen=True, slots=True)
class AttentionCooldown:
    source_ref: str
    eligible_after_epoch: int

    def __post_init__(self) -> None:
        require_identifier(self.source_ref, "source_ref")
        _positive(self.eligible_after_epoch, "eligible_after_epoch")


@dataclass(frozen=True, slots=True)
class AttentionFocusState:
    revision: int
    source_context_revision: int
    policy_id: str
    policy_revision: int
    foreground_focus_ref: str | None
    active_focus_intent_ref: str | None
    secondary_monitor_refs: tuple[str, ...]
    current_turn_owner: str | None
    response_obligation: str | None
    sources: tuple[AttentionSource, ...]
    selection_epoch: int
    last_selected_source_ref: str | None
    same_source_burst: int
    last_selected_priority: AttentionPriority | None
    priority_burst: int
    cooldowns: tuple[AttentionCooldown, ...]
    updated_at: datetime

    def __post_init__(self) -> None:
        require_revision(self.revision, "revision")
        require_revision(self.source_context_revision, "source_context_revision")
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        for name in (
            "foreground_focus_ref",
            "active_focus_intent_ref",
            "current_turn_owner",
            "response_obligation",
            "last_selected_source_ref",
        ):
            _id_or_none(getattr(self, name), name)
        monitors = _ids(self.secondary_monitor_refs, "secondary_monitor_refs")
        if self.foreground_focus_ref in monitors:
            raise ValueError("foregroundはsecondary monitorと重複できません")
        sources = tuple(self.sources)
        if any(not isinstance(item, AttentionSource) for item in sources) or len(
            {item.source_ref for item in sources}
        ) != len(sources):
            raise ValueError("sourcesは一意なAttentionSource配列でなければなりません")
        if any(item.source_context_revision > self.source_context_revision for item in sources):
            raise ValueError("source context revisionはglobal stateを超えられません")
        _positive(self.selection_epoch, "selection_epoch", zero=True)
        _positive(self.same_source_burst, "same_source_burst", zero=True)
        _positive(self.priority_burst, "priority_burst", zero=True)
        if self.last_selected_priority is not None and not isinstance(
            self.last_selected_priority, AttentionPriority
        ):
            raise ValueError("last_selected_priorityが不正です")
        if (self.last_selected_source_ref is None) != (self.same_source_burst == 0) or (
            self.last_selected_priority is None
        ) != (self.priority_burst == 0):
            raise ValueError("fairness selection stateが一致しません")
        cooldowns = tuple(self.cooldowns)
        if (
            any(not isinstance(item, AttentionCooldown) for item in cooldowns)
            or len({item.source_ref for item in cooldowns}) != len(cooldowns)
            or any(
                item.source_ref not in {source.source_ref for source in sources}
                for item in cooldowns
            )
        ):
            raise ValueError("cooldownsが不正です")
        require_aware(self.updated_at, "updated_at")
        object.__setattr__(self, "secondary_monitor_refs", monitors)
        object.__setattr__(
            self, "sources", tuple(sorted(sources, key=lambda item: item.source_ref))
        )
        object.__setattr__(
            self, "cooldowns", tuple(sorted(cooldowns, key=lambda item: item.source_ref))
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "source_context_revision": self.source_context_revision,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "foreground_focus_ref": self.foreground_focus_ref,
            "active_focus_intent_ref": self.active_focus_intent_ref,
            "secondary_monitor_refs": list(self.secondary_monitor_refs),
            "current_turn_owner": self.current_turn_owner,
            "response_obligation": self.response_obligation,
            "sources": [source.to_dict() for source in self.sources],
            "selection_epoch": self.selection_epoch,
            "last_selected_source_ref": self.last_selected_source_ref,
            "same_source_burst": self.same_source_burst,
            "last_selected_priority": None
            if self.last_selected_priority is None
            else self.last_selected_priority.name.lower(),
            "priority_burst": self.priority_burst,
            "cooldowns": [
                {"source_ref": item.source_ref, "eligible_after_epoch": item.eligible_after_epoch}
                for item in self.cooldowns
            ],
            "updated_at": timestamp_to_json(self.updated_at),
        }


@dataclass(frozen=True, slots=True)
class AttentionFocusView:
    revision: int
    source_context_revision: int
    policy_id: str
    policy_revision: int
    foreground_focus_ref: str | None
    active_focus_intent_ref: str | None
    secondary_monitor_refs: tuple[str, ...]
    current_turn_owner: str | None
    response_obligation: str | None

    def __post_init__(self) -> None:
        require_revision(self.revision, "revision")
        require_revision(self.source_context_revision, "source_context_revision")
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        for name in (
            "foreground_focus_ref",
            "active_focus_intent_ref",
            "current_turn_owner",
            "response_obligation",
        ):
            _id_or_none(getattr(self, name), name)
        object.__setattr__(
            self,
            "secondary_monitor_refs",
            _ids(self.secondary_monitor_refs, "secondary_monitor_refs"),
        )

    @classmethod
    def from_state(cls, state: AttentionFocusState) -> AttentionFocusView:
        return cls(
            state.revision,
            state.source_context_revision,
            state.policy_id,
            state.policy_revision,
            state.foreground_focus_ref,
            state.active_focus_intent_ref,
            state.secondary_monitor_refs,
            state.current_turn_owner,
            state.response_obligation,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "source_context_revision": self.source_context_revision,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "foreground_focus_ref": self.foreground_focus_ref,
            "active_focus_intent_ref": self.active_focus_intent_ref,
            "secondary_monitor_refs": list(self.secondary_monitor_refs),
            "current_turn_owner": self.current_turn_owner,
            "response_obligation": self.response_obligation,
        }


@dataclass(frozen=True, slots=True)
class AttentionTransition:
    transition_id: str
    operation: AttentionTransitionOperation
    expected_attention_revision: int
    expected_source_context_revision: int
    occurred_at: datetime
    target_ref: str | None = None
    value: str | None = None
    source_intent_ref: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.transition_id, "transition_id")
        if not isinstance(self.operation, AttentionTransitionOperation):
            raise ValueError("operationが不正です")
        require_revision(self.expected_attention_revision, "expected_attention_revision")
        require_revision(self.expected_source_context_revision, "expected_source_context_revision")
        require_aware(self.occurred_at, "occurred_at")
        _id_or_none(self.target_ref, "target_ref")
        _id_or_none(self.value, "value")
        _id_or_none(self.source_intent_ref, "source_intent_ref")
        targets = {
            AttentionTransitionOperation.ACQUIRE_FOREGROUND,
            AttentionTransitionOperation.ADD_MONITOR,
            AttentionTransitionOperation.REMOVE_MONITOR,
        }
        values = {
            AttentionTransitionOperation.ASSIGN_TURN,
            AttentionTransitionOperation.SET_RESPONSE_OBLIGATION,
        }
        if (self.operation in targets) != (self.target_ref is not None) or (
            self.operation in values
        ) != (self.value is not None):
            raise ValueError("transitionのoperationとpayloadが一致しません")
        if (
            self.operation is AttentionTransitionOperation.ACQUIRE_FOREGROUND
            and self.source_intent_ref is None
        ):
            raise ValueError("acquire foregroundにはsource intent refが必要です")
        if (
            self.operation is not AttentionTransitionOperation.ACQUIRE_FOREGROUND
            and self.source_intent_ref is not None
        ):
            raise ValueError("source intent refはacquire foregroundだけに指定できます")


@dataclass(frozen=True, slots=True)
class ExecutiveTriggerEligibility:
    trigger_id: str
    source_ref: str
    reason_kind: AttentionSourceKind
    priority: AttentionPriority
    source_context_revision: int
    goal_revision: int
    attention_revision: int
    created_at: datetime
    source_revision: int | None = None
    interruption_allowed: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.trigger_id, "trigger_id")
        require_identifier(self.source_ref, "source_ref")
        if not isinstance(self.reason_kind, AttentionSourceKind) or not isinstance(
            self.priority, AttentionPriority
        ):
            raise ValueError("trigger kind又はpriorityが不正です")
        for name in ("source_context_revision", "goal_revision", "attention_revision"):
            require_revision(getattr(self, name), name)
        if self.source_revision is not None:
            require_revision(self.source_revision, "source_revision")
        if type(self.interruption_allowed) is not bool:
            raise ValueError("interruption_allowedはboolでなければなりません")
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class AttentionInterruptionDecision:
    challenger_ref: str
    allowed: bool
    minimum_priority: AttentionPriority

    def __post_init__(self) -> None:
        require_identifier(self.challenger_ref, "challenger_ref")
        if type(self.allowed) is not bool or not isinstance(
            self.minimum_priority, AttentionPriority
        ):
            raise ValueError("interruption decisionが不正です")


@dataclass(frozen=True, slots=True)
class SpeechCandidateSchedulingFact:
    candidate_ref: str
    phase: SpeechCandidateSchedulingPhase
    priority: AttentionPriority
    interruptible: bool
    source_context_revision: int
    attention_revision: int | None = None

    def __post_init__(self) -> None:
        require_identifier(self.candidate_ref, "candidate_ref")
        if (
            not isinstance(self.phase, SpeechCandidateSchedulingPhase)
            or not isinstance(self.priority, AttentionPriority)
            or type(self.interruptible) is not bool
        ):
            raise ValueError("speech scheduling factが不正です")
        require_revision(self.source_context_revision, "source_context_revision")
        if self.attention_revision is not None:
            require_revision(self.attention_revision, "attention_revision")


@dataclass(frozen=True, slots=True)
class SpeechSchedulingView:
    speech_revision: int
    presenting_candidate: SpeechCandidateSchedulingFact | None
    queued_candidates: tuple[SpeechCandidateSchedulingFact, ...]

    def __post_init__(self) -> None:
        require_revision(self.speech_revision, "speech_revision")
        if self.presenting_candidate is not None and not isinstance(
            self.presenting_candidate, SpeechCandidateSchedulingFact
        ):
            raise ValueError("presenting candidateが不正です")
        candidates = tuple(self.queued_candidates)
        if any(not isinstance(item, SpeechCandidateSchedulingFact) for item in candidates) or len(
            {item.candidate_ref for item in candidates}
        ) != len(candidates):
            raise ValueError("queued candidatesが不正です")
        object.__setattr__(self, "queued_candidates", candidates)


@dataclass(frozen=True, slots=True)
class SpeechSchedulingDirective:
    directive_id: str
    operation: SpeechSchedulingOperation
    candidate_ref: str
    source_trigger_ref: str
    expected_speech_revision: int
    attention_revision: int
    reason_kind: AttentionSourceKind
    occurred_at: datetime

    def __post_init__(self) -> None:
        for name in ("directive_id", "candidate_ref", "source_trigger_ref"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.operation, SpeechSchedulingOperation) or not isinstance(
            self.reason_kind, AttentionSourceKind
        ):
            raise ValueError("speech scheduling directiveが不正です")
        require_revision(self.expected_speech_revision, "expected_speech_revision")
        require_revision(self.attention_revision, "attention_revision")
        require_aware(self.occurred_at, "occurred_at")
