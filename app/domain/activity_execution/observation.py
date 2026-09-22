"""活動要求とは独立した実行観測の不変契約と、所有者内の純粋な受理検査。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.contracts import ExecutionResult, ExecutionStatus, RevisionVector
from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    require_revision,
    thaw_json,
    utc_instant,
)

from .contracts import ExecutionEffectKind, ExecutionEffectUncertainty

_FAILURES = frozenset(
    {ExecutionStatus.FAILED, ExecutionStatus.CANCELLED, ExecutionStatus.TIMED_OUT}
)
_MILESTONES = frozenset({ExecutionStatus.OBSERVABLE, ExecutionStatus.APPLIED})
_STATUSES = _FAILURES | _MILESTONES | {ExecutionStatus.COMPLETED}


def same_json(left: JsonValue, right: JsonValue) -> bool:
    """Pythonのbool/int同値判定を使わず、JSON型を含めて照合する。"""
    return json.dumps(thaw_json(left), sort_keys=True, ensure_ascii=True) == json.dumps(
        thaw_json(right), sort_keys=True, ensure_ascii=True
    )


def same_observation(left: TrustedExecutionObservation, right: TrustedExecutionObservation) -> bool:
    return (
        left == right
        and same_json(left.details, right.details)
        and all(
            same_json(a.payload, b.payload)
            for a, b in zip(left.effects, right.effects, strict=True)
        )
    )


def observation_identity(*parts: str) -> str:
    """区切り文字を含む識別子も衝突させず、同じ入力へ同じ識別子を返す。"""
    return "observed:" + json.dumps(parts, ensure_ascii=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ExecutionObservationSourceBinding:
    source_contract_id: str
    source_contract_revision: int

    def __post_init__(self) -> None:
        require_identifier(self.source_contract_id, "source_contract_id")
        require_revision(self.source_contract_revision, "source_contract_revision")


@dataclass(frozen=True, slots=True)
class ExecutionObservationSourceRule:
    source: ExecutionObservationSourceBinding
    allowed_statuses: tuple[ExecutionStatus, ...]
    allowed_effect_types: tuple[str, ...]
    allowed_effect_kinds: tuple[ExecutionEffectKind, ...] = (ExecutionEffectKind.OBSERVABLE,)
    terminal_requires_prior_effect: bool = False

    def __post_init__(self) -> None:
        if type(self.terminal_requires_prior_effect) is not bool:
            raise ValueError("終端の先行effect制約が不正です")
        if not isinstance(self.source, ExecutionObservationSourceBinding):
            raise ValueError("source契約が不正です")
        statuses = tuple(self.allowed_statuses)
        kinds = tuple(self.allowed_effect_kinds)
        types = tuple(self.allowed_effect_types)
        if not statuses or any(
            not isinstance(s, ExecutionStatus) or s not in _STATUSES for s in statuses
        ):
            raise ValueError("許可statusが不正です")
        if not kinds or any(not isinstance(k, ExecutionEffectKind) for k in kinds):
            raise ValueError("許可effect kindが不正です")
        if not types or any(not isinstance(t, str) or not t.strip() for t in types):
            raise ValueError("許可effect typeが不正です")
        if any(len(set(v)) != len(v) for v in (statuses, kinds, types)):
            raise ValueError("source ruleに重複があります")
        object.__setattr__(self, "allowed_statuses", statuses)
        object.__setattr__(self, "allowed_effect_types", types)
        object.__setattr__(self, "allowed_effect_kinds", kinds)


@dataclass(frozen=True, slots=True)
class ExecutionObservationIngressPolicy:
    policy_id: str
    policy_revision: int
    source_rules: tuple[ExecutionObservationSourceRule, ...]

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        rules = tuple(self.source_rules)
        if any(not isinstance(r, ExecutionObservationSourceRule) for r in rules):
            raise ValueError("source rulesが不正です")
        if len({r.source for r in rules}) != len(rules):
            raise ValueError("source ruleが重複しています")
        object.__setattr__(self, "source_rules", rules)


@dataclass(frozen=True, slots=True)
class ExecutionObservationProvenance:
    source_decision_id: str
    source_event_ids: tuple[str, ...]
    revisions: RevisionVector
    trace_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.source_decision_id, "source_decision_id")
        events = tuple(self.source_event_ids)
        if not events or any(not isinstance(e, str) or not e.strip() for e in events):
            raise ValueError("source event IDsが不正です")
        if len(set(events)) != len(events) or not isinstance(self.revisions, RevisionVector):
            raise ValueError("観測の由来が不正です")
        if self.trace_id is not None:
            require_identifier(self.trace_id, "trace_id")
        object.__setattr__(self, "source_event_ids", events)


@dataclass(frozen=True, slots=True)
class ObservedExecutionEffectEvidence:
    effect_id: str
    effect_type: str
    subject_ref: str
    kind: ExecutionEffectKind
    payload: JsonValue

    def __post_init__(self) -> None:
        for name in ("effect_id", "effect_type", "subject_ref"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.kind, ExecutionEffectKind):
            raise ValueError("effect kindが不正です")
        value = freeze_json(self.payload)
        if not isinstance(value, Mapping):
            raise ValueError("effect payloadはobjectが必要です")
        object.__setattr__(self, "payload", value)


@dataclass(frozen=True, slots=True)
class TrustedExecutionObservation:
    observation_id: str
    execution_id: str
    source: ExecutionObservationSourceBinding
    subject_ref: str
    status: ExecutionStatus
    committed_at: datetime
    started_at: datetime | None
    occurred_at: datetime
    provenance: ExecutionObservationProvenance
    details: JsonValue = field(default_factory=dict)
    effects: tuple[ObservedExecutionEffectEvidence, ...] = ()
    effect_uncertainty: ExecutionEffectUncertainty = ExecutionEffectUncertainty.NONE

    def __post_init__(self) -> None:
        for name in ("observation_id", "execution_id", "subject_ref"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.source, ExecutionObservationSourceBinding) or not isinstance(
            self.provenance, ExecutionObservationProvenance
        ):
            raise ValueError("観測のsourceまたは由来が不正です")
        if not isinstance(self.status, ExecutionStatus) or self.status not in _STATUSES:
            raise ValueError("観測statusが不正です")
        times = (
            (self.committed_at, self.occurred_at)
            if self.started_at is None
            else (self.committed_at, self.started_at, self.occurred_at)
        )
        for t in times:
            require_aware(t, "観測時刻")
        if any(utc_instant(a) > utc_instant(b) for a, b in zip(times, times[1:], strict=False)):
            raise ValueError("観測時刻が逆行しています")
        if self.status not in _FAILURES and self.started_at is None:
            raise ValueError("開始済み観測にはOwnerの開始時刻が必要です")
        effects = tuple(self.effects)
        if any(not isinstance(e, ObservedExecutionEffectEvidence) for e in effects):
            raise ValueError("観測effectが不正です")
        if len({e.effect_id for e in effects}) != len(effects):
            raise ValueError("effect identityが重複しています")
        if any(e.subject_ref != self.subject_ref for e in effects):
            raise ValueError("effect subjectが一致しません")
        if self.status in _MILESTONES and not effects:
            raise ValueError("観測milestoneには確認済みeffectが必要です")
        if effects and self.status in _FAILURES:
            raise ValueError("失敗終端観測は新しい確認済みeffectを導入できません")
        if self.status is ExecutionStatus.OBSERVABLE and any(
            e.kind is ExecutionEffectKind.APPLIED for e in effects
        ):
            raise ValueError("OBSERVABLEへAPPLIED effectを導入できません")
        if not isinstance(self.effect_uncertainty, ExecutionEffectUncertainty):
            raise ValueError("effect uncertaintyが不正です")
        if (
            self.effect_uncertainty is not ExecutionEffectUncertainty.NONE
            and self.status not in _FAILURES
        ):
            raise ValueError("未確認effectは失敗終端だけに保持できます")
        if self.started_at is None and (
            effects or self.effect_uncertainty is not ExecutionEffectUncertainty.NONE
        ):
            raise ValueError("未開始観測にeffectまたは未確認effectを付与できません")
        details = freeze_json(self.details)
        if not isinstance(details, Mapping):
            raise ValueError("観測detailsはobjectが必要です")
        object.__setattr__(self, "details", details)
        object.__setattr__(self, "effects", effects)


@dataclass(frozen=True, slots=True)
class ObservedExecutionFactRecord:
    execution_id: str
    source: ExecutionObservationSourceBinding
    subject_ref: str
    result: ExecutionResult
    effects: tuple[ObservedExecutionEffectEvidence, ...]
    effect_uncertainty: ExecutionEffectUncertainty
    provenance: ExecutionObservationProvenance
    record_revision: int
    latest_observation_id: str
    committed_at: datetime
    started_at: datetime | None

    def __post_init__(self) -> None:
        require_revision(self.record_revision, "record_revision")
        require_identifier(self.latest_observation_id, "latest_observation_id")
        effects = tuple(self.effects)
        if (
            not isinstance(self.source, ExecutionObservationSourceBinding)
            or not isinstance(self.provenance, ExecutionObservationProvenance)
            or not isinstance(self.result, ExecutionResult)
            or any(not isinstance(e, ObservedExecutionEffectEvidence) for e in effects)
        ):
            raise ValueError("観測recordの型が不正です")
        if (
            self.result.command_id
            != observation_identity(
                self.source.source_contract_id,
                str(self.source.source_contract_revision),
                self.execution_id,
            )
            or self.result.revisions != self.provenance.revisions
        ):
            raise ValueError("観測recordのidentityまたは由来が一致しません")
        if tuple(e.effect_id for e in effects) != self.result.effect_refs:
            raise ValueError("観測recordのeffect evidenceと参照が一致しません")
        if any(e.subject_ref != self.subject_ref for e in effects):
            raise ValueError("観測recordのsubjectが一致しません")
        if not isinstance(self.effect_uncertainty, ExecutionEffectUncertainty) or (
            self.effect_uncertainty is not ExecutionEffectUncertainty.NONE
            and self.result.status not in _FAILURES
        ):
            raise ValueError("観測recordの未確定性が不正です")
        object.__setattr__(self, "effects", effects)


def accept_observation(
    observation: TrustedExecutionObservation,
    before: ObservedExecutionFactRecord | None,
) -> ObservedExecutionFactRecord:
    """検査と遷移を完了してから返す。保存は同じ#329 Authorityだけが行う。"""
    o = observation
    effects = {} if before is None else {e.effect_id: e for e in before.effects}
    if before is not None:
        if (
            before.source,
            before.subject_ref,
            before.provenance,
            before.committed_at,
            before.started_at,
        ) != (o.source, o.subject_ref, o.provenance, o.committed_at, o.started_at):
            raise ValueError("同一executionのsource・subject・由来・開始時刻が矛盾しています")
        if before.result.status not in _MILESTONES:
            raise ValueError("終端executionを再開できません")
        result = before.result
    else:
        identity = observation_identity(
            o.source.source_contract_id, str(o.source.source_contract_revision), o.execution_id
        )
        result = ExecutionResult(
            identity, ExecutionStatus.REQUESTED, o.committed_at, o.provenance.revisions
        )
        result = result.transition_to(ExecutionStatus.ACCEPTED, o.committed_at)
        if o.started_at is not None:
            result = result.transition_to(ExecutionStatus.STARTED, o.started_at)
    for effect in o.effects:
        previous = effects.get(effect.effect_id)
        if previous is not None and (
            previous != effect or not same_json(previous.payload, effect.payload)
        ):
            raise ValueError("同一effect identityの内容が矛盾しています")
        effects[effect.effect_id] = effect
    result = result.transition_to(
        o.status, o.occurred_at, details=o.details, effect_refs=tuple(effects)
    )
    return ObservedExecutionFactRecord(
        o.execution_id,
        o.source,
        o.subject_ref,
        result,
        tuple(effects.values()),
        o.effect_uncertainty,
        o.provenance,
        1 if before is None else before.record_revision + 1,
        o.observation_id,
        o.committed_at,
        o.started_at,
    )
