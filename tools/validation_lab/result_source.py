"""保存済みの検証証拠を、内容の脱落を許さず既存の型へ復元する。"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from app.domain.contracts.common import JsonValue, thaw_json
from app.subsystems.validation.contracts import (
    DelayInjection,
    FailureInjection,
    Gate,
    InjectedFailure,
    LabMode,
    LabRunSpec,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    ValidationRunResult,
    WorkInterval,
)
from tools.validation_lab.review import _date, _object, _string, load_source


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("検証証拠の整数項目が不正です")
    return value


def _items(value: object) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise ValueError("検証証拠の配列項目が不正です")
    return value


def _strings(value: object) -> tuple[str, ...]:
    return tuple(_string(x) for x in _items(value))


def _optional(value: object) -> str | None:
    return None if value is None else _string(value)


def _delay(value: object) -> DelayInjection:
    item = _object(value)
    duration = item["duration"]
    if type(duration) not in (int, float):
        raise ValueError("検証証拠の遅延時間が不正です")
    return DelayInjection(
        _string(item["stage"]), cast(float, duration), _integer(item["activation_count"])
    )


def _failure(value: object) -> FailureInjection:
    item = _object(value)
    return FailureInjection(
        _string(item["stage"]),
        InjectedFailure(_string(item["closed_failure_kind"])),
        _integer(item["activation_count"]),
    )


def _interval(value: object) -> WorkInterval:
    item = _object(value)
    start, end = _integer(item["started_ns"]), _integer(item["completed_ns"])
    iteration = _integer(item["iteration"])
    if start < 0 or end < start or iteration < 0:
        raise ValueError("検証証拠の時系列が不正です")
    return WorkInterval(
        _string(item["stage"]), iteration, start, end, RunStatus(_string(item["status"]))
    )


def decode_result(source: Mapping[str, object]) -> ValidationRunResult:
    run, provenance = _object(source["run_spec"]), _object(source["target_provenance"])
    spec = LabRunSpec(
        _string(run["run_id"]),
        _string(run["lab_kind"]),
        LabMode(_string(run["mode"])),
        _string(run["target_module"]),
        _string(run["target_contract_revision"]),
        _string(run["scenario_id"]),
        _string(run["fixture_revision"]),
        _strings(run["provider_policy_refs"]),
        _integer(run["repeat_count"]),
        _date(run["requested_at"]),
        None if run["seed"] is None else _integer(run["seed"]),
        tuple(_delay(x) for x in _items(run["delay_injections"])),
        tuple(_failure(x) for x in _items(run["failure_injections"])),
    )
    origin = ProductionTargetProvenance(
        _string(provenance["git_head"]),
        _string(provenance["branch"]),
        _strings(provenance["module_contract_ids"]),
        _strings(provenance["role_schema_ids"]),
        _optional(provenance["character_definition_revision"]),
        _optional(provenance["provider_config_revision"]),
        _optional(provenance["runtime_policy_revision"]),
    )
    stages = tuple(_object(x) for x in _items(source["stage_results"]))
    result = ValidationRunResult(
        spec,
        origin,
        ValidationFixture(
            spec.scenario_id,
            spec.fixture_revision,
            cast(JsonValue, source["typed_inputs"]),
            cast(JsonValue, source["human_context"]),
        ),
        RunStatus(_string(source["status"])),
        tuple(
            TargetObservation(
                RunStatus(_string(x["status"])),
                Gate(_string(x["machine_gate"])),
                cast(JsonValue, x["typed_outputs"]),
            )
            for x in stages
        ),
        tuple(_interval(x) for x in _items(source["timeline"])),
        Gate(_string(source["machine_gate"])),
        _strings(source["blockers"]),
        _date(source["completed_at"]),
        tuple(cast(JsonValue, x) for x in _items(source["provider_diagnostics"])),
        _integer(source["diagnostics_dropped"]),
    )
    if result.completed_at < spec.requested_at or result.diagnostics_dropped < 0:
        raise ValueError("検証証拠の完了日時または診断件数が不正です")
    # 未知項目や評価済み状態を落としたまま復元したことにしない。
    before = json.dumps(thaw_json(cast(JsonValue, source)), sort_keys=True, ensure_ascii=False)
    after = json.dumps(result.to_dict(), sort_keys=True, ensure_ascii=False)
    if before != after:
        raise ValueError("元の証拠を完全に保持できないため比較への読込みを拒否しました")
    return result


def load_result(path: Path) -> tuple[ValidationRunResult, str]:
    source, digest = load_source(path)
    return decode_result(source), digest
