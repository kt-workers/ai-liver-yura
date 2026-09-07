"""検証の実行条件と、製品の状態変更権限を持たない証拠データ。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.contracts.common import JsonValue, freeze_json, thaw_json


class LabMode(str, Enum):
    ISOLATION = "ISOLATION"
    ADJACENT = "ADJACENT"
    INTEGRATED = "INTEGRATED"
    SYSTEM_SLICE = "SYSTEM_SLICE"


class RunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    BLOCKED_UPSTREAM = "BLOCKED_UPSTREAM"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    PRODUCT_FAILED = "PRODUCT_FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    HARNESS_FAILED = "HARNESS_FAILED"


class InjectedFailure(str, Enum):
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class Gate(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


def identifier(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("識別子は空でない文字列で指定してください")


def positive(value: int) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("上限と回数は1以上の整数で指定してください")


def aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("日時には時間帯が必要です")


@dataclass(frozen=True)
class LabPolicy:
    max_repeats: int
    max_tasks: int
    max_intervals: int
    max_export_bytes: int
    timeout_seconds: float
    max_retained_results: int

    def __post_init__(self) -> None:
        for value in (
            self.max_repeats,
            self.max_tasks,
            self.max_intervals,
            self.max_export_bytes,
            self.max_retained_results,
        ):
            positive(value)
        if (
            type(self.timeout_seconds) not in (int, float)
            or not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("実行期限は有限の正数で指定してください")


@dataclass(frozen=True)
class DelayInjection:
    stage: str
    duration: float
    activation_count: int

    def __post_init__(self) -> None:
        identifier(self.stage)
        positive(self.activation_count)
        if (
            type(self.duration) not in (int, float)
            or not isfinite(self.duration)
            or self.duration < 0
        ):
            raise ValueError("遅延は有限の非負秒数で指定してください")


@dataclass(frozen=True)
class FailureInjection:
    stage: str
    closed_failure_kind: InjectedFailure
    activation_count: int

    def __post_init__(self) -> None:
        identifier(self.stage)
        positive(self.activation_count)
        if not isinstance(self.closed_failure_kind, InjectedFailure):
            raise ValueError("失敗注入の分類が不正です")


@dataclass(frozen=True)
class LabRunSpec:
    run_id: str
    lab_kind: str
    mode: LabMode
    target_module: str
    target_contract_revision: str
    scenario_id: str
    fixture_revision: str
    provider_policy_refs: tuple[str, ...]
    repeat_count: int
    requested_at: datetime
    seed: int | None = None
    delay_injections: tuple[DelayInjection, ...] = ()
    failure_injections: tuple[FailureInjection, ...] = ()

    def __post_init__(self) -> None:
        for value in (
            self.run_id,
            self.lab_kind,
            self.target_module,
            self.target_contract_revision,
            self.scenario_id,
            self.fixture_revision,
        ):
            identifier(value)
        if not isinstance(self.mode, LabMode):
            raise ValueError("検証範囲が不正です")
        positive(self.repeat_count)
        injections = tuple(self.delay_injections)
        if any(not isinstance(item, DelayInjection) for item in injections):
            raise ValueError("遅延注入の型が不正です")
        if len({item.stage for item in injections}) != len(injections):
            raise ValueError("同じ段階の遅延注入は重複できません")
        object.__setattr__(self, "delay_injections", injections)
        failures = tuple(self.failure_injections)
        if any(not isinstance(item, FailureInjection) for item in failures):
            raise ValueError("失敗注入の型が不正です")
        if len({item.stage for item in failures}) != len(failures):
            raise ValueError("同じ段階の失敗注入は重複できません")
        object.__setattr__(self, "failure_injections", failures)
        aware(self.requested_at)
        refs = tuple(self.provider_policy_refs)
        if len(refs) != len(set(refs)):
            raise ValueError("提供サービス方針の参照は重複できません")
        for ref in refs:
            identifier(ref)
        object.__setattr__(self, "provider_policy_refs", refs)
        if self.seed is not None and type(self.seed) is not int:
            raise ValueError("乱数の種は整数で指定してください")


@dataclass(frozen=True)
class ProductionTargetProvenance:
    git_head: str
    branch: str
    module_contract_ids: tuple[str, ...]
    role_schema_ids: tuple[str, ...]
    character_definition_revision: str | None = None
    provider_config_revision: str | None = None
    runtime_policy_revision: str | None = None

    def __post_init__(self) -> None:
        if len(self.git_head) != 40 or any(c not in "0123456789abcdef" for c in self.git_head):
            raise ValueError("製品の出典には完全なcommit SHAが必要です")
        identifier(self.branch)
        for name in ("module_contract_ids", "role_schema_ids"):
            values = tuple(getattr(self, name))
            if name == "module_contract_ids" and not values:
                raise ValueError("製品契約の参照が必要です")
            for value in values:
                identifier(value)
            if len(set(values)) != len(values):
                raise ValueError("出典の参照は重複できません")
            object.__setattr__(self, name, values)
        for value in (
            self.character_definition_revision,
            self.provider_config_revision,
            self.runtime_policy_revision,
        ):
            if value is not None:
                identifier(value)


@dataclass(frozen=True)
class ValidationFixture:
    scenario_id: str
    fixture_revision: str
    typed_inputs: JsonValue
    human_context: JsonValue

    def __post_init__(self) -> None:
        identifier(self.scenario_id)
        identifier(self.fixture_revision)
        object.__setattr__(self, "typed_inputs", freeze_json(self.typed_inputs))
        object.__setattr__(self, "human_context", freeze_json(self.human_context))


@dataclass(frozen=True)
class WorkInterval:
    stage: str
    iteration: int
    started_ns: int
    completed_ns: int
    status: RunStatus

    def overlaps(self, other: WorkInterval) -> bool:
        return max(self.started_ns, other.started_ns) < min(self.completed_ns, other.completed_ns)


@dataclass(frozen=True)
class TargetObservation:
    """登録済みの製品接続が公開可能な成果だけを投影する。"""

    status: RunStatus
    machine_gate: Gate
    typed_outputs: JsonValue

    def __post_init__(self) -> None:
        if not isinstance(self.status, RunStatus) or not isinstance(self.machine_gate, Gate):
            raise ValueError("観測状態が不正です")
        object.__setattr__(self, "typed_outputs", freeze_json(self.typed_outputs))


@dataclass(frozen=True)
class ValidationRunResult:
    spec: LabRunSpec
    target_provenance: ProductionTargetProvenance
    fixture: ValidationFixture
    status: RunStatus
    stage_results: tuple[TargetObservation, ...]
    timeline: tuple[WorkInterval, ...]
    machine_gate: Gate
    blockers: tuple[str, ...]
    completed_at: datetime
    provider_diagnostics: tuple[JsonValue, ...] = ()
    diagnostics_dropped: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "run_spec": {
                "run_id": self.spec.run_id,
                "lab_kind": self.spec.lab_kind,
                "mode": self.spec.mode.value,
                "target_module": self.spec.target_module,
                "target_contract_revision": self.spec.target_contract_revision,
                "scenario_id": self.spec.scenario_id,
                "fixture_revision": self.spec.fixture_revision,
                "provider_policy_refs": list(self.spec.provider_policy_refs),
                "repeat_count": self.spec.repeat_count,
                "seed": self.spec.seed,
                "requested_at": self.spec.requested_at.isoformat(),
                "failure_injections": [
                    {
                        "stage": x.stage,
                        "closed_failure_kind": x.closed_failure_kind.value,
                        "activation_count": x.activation_count,
                    }
                    for x in self.spec.failure_injections
                ],
                "delay_injections": [
                    {
                        "stage": x.stage,
                        "duration": x.duration,
                        "activation_count": x.activation_count,
                    }
                    for x in self.spec.delay_injections
                ],
            },
            "target_provenance": {
                "git_head": self.target_provenance.git_head,
                "branch": self.target_provenance.branch,
                "module_contract_ids": list(self.target_provenance.module_contract_ids),
                "role_schema_ids": list(self.target_provenance.role_schema_ids),
                "character_definition_revision": (
                    self.target_provenance.character_definition_revision
                ),
                "provider_config_revision": self.target_provenance.provider_config_revision,
                "runtime_policy_revision": self.target_provenance.runtime_policy_revision,
            },
            "typed_inputs": thaw_json(self.fixture.typed_inputs),
            "human_context": thaw_json(self.fixture.human_context),
            "status": self.status.value,
            "machine_gate": self.machine_gate.value,
            "human_evaluation": {"status": "UNRATED"},
            "provider_diagnostics": [thaw_json(x) for x in self.provider_diagnostics],
            "diagnostics_dropped": self.diagnostics_dropped,
            "stage_results": [
                {
                    "status": x.status.value,
                    "machine_gate": x.machine_gate.value,
                    "typed_outputs": thaw_json(x.typed_outputs),
                }
                for x in self.stage_results
            ],
            "timeline": [
                {
                    "stage": x.stage,
                    "iteration": x.iteration,
                    "started_ns": x.started_ns,
                    "completed_ns": x.completed_ns,
                    "status": x.status.value,
                }
                for x in self.timeline
            ],
            "blockers": list(self.blockers),
            "completed_at": self.completed_at.isoformat(),
        }

    def export_markdown(self, maximum_bytes: int) -> str:
        payload = json.loads(self.export_json(maximum_bytes))
        pretty = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)
        result = "# 検証記録\n\n" + "\n".join("    " + line for line in pretty.splitlines()) + "\n"
        if len(result.encode("utf-8")) > maximum_bytes:
            raise ValueError("検証記録の書出し容量を超えています")
        return result

    def export_json(self, maximum_bytes: int) -> str:
        positive(maximum_bytes)
        payload = self.to_dict()
        _reject_sensitive_keys(payload)
        result = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(result.encode("utf-8")) > maximum_bytes:
            raise ValueError("検証記録の書出し容量を超えています")
        return result


def _reject_sensitive_keys(value: object) -> None:
    """登録接続の公開用投影に加え、既知の秘密項目の混入を拒否する。"""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in {
                "authorization",
                "api_key",
                "access_token",
                "password",
                "provider_response",
                "raw_exception",
                "raw_prompt",
            }:
                raise ValueError("検証記録に非公開項目が含まれています")
            _reject_sensitive_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_sensitive_keys(item)
