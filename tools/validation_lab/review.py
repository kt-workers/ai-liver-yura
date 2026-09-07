"""保存済みの検証証拠を表示し、人間が入力した評価を別の証拠として保存する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from app.domain.contracts.common import JsonValue, freeze_json, thaw_json
from app.subsystems.validation.contracts import (
    Gate,
    LabMode,
    RunStatus,
    _reject_sensitive_keys,
    aware,
    identifier,
)
from app.subsystems.validation.evaluation import DimensionRating, HumanEvaluation, RatingState

MAXIMUM_BYTES = 1_000_000
MAXIMUM_COMMENT_BYTES = 8_000
MAXIMUM_DIMENSIONS = 16


def _object(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("検証証拠の構造が不正です")
    return cast(Mapping[str, object], value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("検証証拠の文字列が不正です")
    return value


def _date(value: object) -> datetime:
    result = datetime.fromisoformat(_string(value))
    aware(result)
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("検証証拠の項目が重複しています")
        result[key] = value
    return result


def load_source(path: Path) -> tuple[Mapping[str, object], str]:
    with path.open("rb") as stream:
        raw = stream.read(MAXIMUM_BYTES + 1)
    if len(raw) > MAXIMUM_BYTES:
        raise ValueError("検証証拠が読取容量を超えています")
    payload = _object(json.loads(raw, object_pairs_hook=_unique_object))
    _reject_sensitive_keys(payload)
    # 元の証拠を再計算・修正せず、評価に必要な部分の構造だけを確認する。
    run = _object(payload.get("run_spec"))
    identifier(_string(run.get("run_id")))
    LabMode(_string(run.get("mode")))
    if RunStatus(_string(payload.get("status"))) is not RunStatus.COMPLETED:
        raise ValueError("完了した実出力を持つ検証証拠が必要です")
    Gate(_string(payload.get("machine_gate")))
    _object(payload.get("target_provenance"))
    _date(payload.get("completed_at"))
    if not payload.get("human_context") or "typed_inputs" not in payload:
        raise ValueError("入力に由来する状況説明と型付き入力が必要です")
    stages = payload.get("stage_results")
    if not isinstance(stages, list) or not stages:
        raise ValueError("評価する実際の出力が必要です")
    for stage in stages:
        record = _object(stage)
        if "typed_outputs" not in record or record["typed_outputs"] is None:
            raise ValueError("評価する実際の出力が必要です")
    # 非有限数など、既存の証拠契約が許さないJSON値も表示前に拒否する。
    frozen = freeze_json(cast(JsonValue, payload))
    return _object(frozen), hashlib.sha256(raw).hexdigest()


def evaluate(
    source: Mapping[str, object],
    *,
    evaluator_id: str,
    dimensions: tuple[str, ...],
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> HumanEvaluation:
    identifier(evaluator_id)
    if not 1 <= len(dimensions) <= MAXIMUM_DIMENSIONS or len(set(dimensions)) != len(dimensions):
        raise ValueError("評価項目の数または重複が不正です")
    for dimension in dimensions:
        identifier(dimension)
    run = _object(source["run_spec"])
    write("入力の状況と実出力を確認して評価してください。機械判定は評価後の証拠に保持します。")
    write("記録された検証範囲の診断評価です。正式な人間による完成確認とは別に保存します。")
    for label, value in (
        ("検証範囲", run["mode"]),
        ("入力に由来する状況説明", source["human_context"]),
        ("型付き入力", source["typed_inputs"]),
        (
            "実際の出力",
            [
                _object(x)["typed_outputs"]
                for x in cast(tuple[object, ...], source["stage_results"])
            ],
        ),
    ):
        write(label)
        write(
            json.dumps(thaw_json(freeze_json(cast(JsonValue, value))), ensure_ascii=False, indent=2)
        )
    write("1: 合格、2: 不合格、3: 対象外、q: 評価を保存せず終了")
    choices = {"1": RatingState.PASS, "2": RatingState.FAIL, "3": RatingState.NOT_APPLICABLE}
    ratings: list[DimensionRating] = []
    for dimension in dimensions:
        while True:
            answer = read(f"{json.dumps(dimension, ensure_ascii=False)} の評価: ").strip()
            if answer.lower() == "q":
                raise EOFError()
            if answer in choices:
                ratings.append(DimensionRating(dimension, choices[answer]))
                break
            write("1、2、3、qのいずれかを入力してください。")
    comment = read("評価コメント（空欄可）: ")
    if len(comment.encode("utf-8")) > MAXIMUM_COMMENT_BYTES:
        raise ValueError("評価コメントが容量上限を超えています")
    rated_at = now()
    if rated_at < _date(source["completed_at"]):
        raise ValueError("評価日時は検証完了以降でなければなりません")
    return HumanEvaluation(_string(run["run_id"]), evaluator_id, tuple(ratings), comment, rated_at)


def save_review(
    output: Path, source: Mapping[str, object], digest: str, evaluation: HumanEvaluation
) -> None:
    if evaluation.run_id != _object(source["run_spec"])["run_id"]:
        raise ValueError("評価と元の検証の識別子が一致しません")
    payload = {
        "evaluation_scope": "diagnostic_human_review",
        "source_artifact_sha256": digest,
        "run_result": thaw_json(cast(JsonValue, source)),
        "human_evaluation": evaluation.to_dict(),
    }
    _reject_sensitive_keys(payload)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
    markdown = (
        "# 人間による検証評価\n\n"
        + "\n".join("    " + line for line in encoded.splitlines())
        + "\n"
    )
    if max(len(encoded.encode("utf-8")), len(markdown.encode("utf-8"))) > MAXIMUM_BYTES:
        raise ValueError("評価証拠が書出し容量を超えています")
    # 新しい保存先だけを確保し、元の証拠と過去の評価を上書きしない。
    output.mkdir(parents=True, exist_ok=False)
    (output / "review.json").write_text(encoded + "\n", encoding="utf-8")
    (output / "review.md").write_text(markdown, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="保存済み検証証拠に人間の評価を記録します")
    parser.add_argument("source", type=Path, help="検証で書き出したresult.json")
    parser.add_argument("--output", type=Path, required=True, help="新しい評価保存先")
    parser.add_argument("--evaluator", required=True, help="実際に評価する人の識別子")
    parser.add_argument(
        "--dimension", action="append", required=True, help="評価項目（複数指定可）"
    )
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("評価保存先は未作成の場所を指定してください")
        source, digest = load_source(args.source)
        evaluation = evaluate(source, evaluator_id=args.evaluator, dimensions=tuple(args.dimension))
        save_review(args.output, source, digest, evaluation)
        print("人間が入力した評価を保存しました。元の検証結果は保持しています。")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("評価を中断しました。完了した評価は保存していません。")
        return 2
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print("証拠の読取または評価の保存に失敗しました。入力と新しい保存先を確認してください。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
