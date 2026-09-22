"""実行中の匿名比較へ人間の評価を入力し、完了後の対応を保存する。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from app.domain.contracts.common import JsonValue, thaw_json
from app.subsystems.validation.contracts import _reject_sensitive_keys, identifier
from app.subsystems.validation.evaluation import BlindComparison, DimensionRating, RatingState
from tools.validation_lab.review import (
    MAXIMUM_BYTES,
    MAXIMUM_COMMENT_BYTES,
    MAXIMUM_DIMENSIONS,
    _object,
    _string,
)


def evaluate_blind(
    comparison: BlindComparison,
    *,
    evaluator_id: str,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> JsonValue:
    """匿名表示のまま全候補を評価し、完了した場合だけ元の結果との対応を返す。"""
    identifier(evaluator_id)
    view = _object(comparison.view())
    _reject_sensitive_keys(view)
    encoded = json.dumps(thaw_json(cast(JsonValue, view)), ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAXIMUM_BYTES:
        raise ValueError("比較表示が容量上限を超えています")
    dimensions = tuple(_string(x) for x in cast(tuple[object, ...], view["dimensions"]))
    write("匿名候補の入力状況と実出力を確認して評価してください。")
    write("全候補を評価した後に対応を開示します。正式な完成確認とは別の診断評価です。")
    choices = {"1": RatingState.PASS, "2": RatingState.FAIL, "3": RatingState.NOT_APPLICABLE}
    for value in cast(tuple[object, ...], view["candidates"]):
        candidate = _object(value)
        if candidate["rating_status"] == "RECORDED":
            continue
        label = _string(candidate["label"])
        write(f"比較候補: {label}")
        for heading, key in (
            ("入力に由来する状況説明", "human_context"),
            ("型付き入力", "typed_inputs"),
            ("実際の出力", "typed_outputs"),
        ):
            write(heading)
            write(
                json.dumps(thaw_json(cast(JsonValue, candidate[key])), ensure_ascii=False, indent=2)
            )
        write("1: 合格、2: 不合格、3: 対象外、q: 対応を開示せず中断")
        ratings = []
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
        # recordの戻り値には実行識別子が含まれるため、評価途中には表示しない。
        comparison.record(
            label,
            evaluator_id=evaluator_id,
            ratings=tuple(ratings),
            comment=comment,
            rated_at=now(),
        )
    return comparison.reveal()


def save_blind_review(
    output: Path, comparison: BlindComparison, *, source_digests: Mapping[str, str] | None = None
) -> None:
    """評価完了を再確認し、元結果を含む対応表を新しい場所へ保存する。"""
    payload = {
        "evaluation_scope": "diagnostic_blind_review",
        "comparison": thaw_json(comparison.reveal()),
    }
    if source_digests is not None:
        payload["source_artifact_sha256"] = dict(source_digests)
    _reject_sensitive_keys(payload)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
    markdown = (
        "# 匿名比較の評価と対応\n\n"
        + "\n".join("    " + line for line in encoded.splitlines())
        + "\n"
    )
    if max(len(encoded.encode("utf-8")), len(markdown.encode("utf-8"))) > MAXIMUM_BYTES:
        raise ValueError("比較の評価証拠が書出し容量を超えています")
    output.mkdir(parents=True, exist_ok=False)
    (output / "comparison.json").write_text(encoded + "\n", encoding="utf-8")
    (output / "comparison.md").write_text(markdown, encoding="utf-8")


def main() -> int:
    from tools.validation_lab.result_source import load_result

    parser = argparse.ArgumentParser(description="保存済み検証結果を匿名比較して評価を保存します")
    parser.add_argument("sources", type=Path, nargs="+", help="比較するresult.json（2〜8件）")
    parser.add_argument("--output", type=Path, required=True, help="新しい評価保存先")
    parser.add_argument("--assignment", required=True, help="比較割当の識別子")
    parser.add_argument("--seed", type=int, required=True, help="割当を固定する整数")
    parser.add_argument("--evaluator", required=True, help="実際に評価する人の識別子")
    parser.add_argument(
        "--dimension", action="append", required=True, help="評価項目（複数指定可）"
    )
    parser.add_argument(
        "--identity-label", action="append", default=[], help="隠すモデル名などの表記"
    )
    args = parser.parse_args()
    try:
        if args.output.exists() or not 2 <= len(args.sources) <= 8:
            raise ValueError("新しい保存先と上限以内の比較候補が必要です")
        if not 1 <= len(args.dimension) <= MAXIMUM_DIMENSIONS:
            raise ValueError("評価項目数が上限を超えています")
        loaded = tuple(load_result(path) for path in args.sources)
        comparison = BlindComparison(
            args.assignment,
            tuple(result for result, _ in loaded),
            tuple(args.dimension),
            seed=args.seed,
            max_candidates=8,
            max_comment_bytes=MAXIMUM_COMMENT_BYTES,
            identity_labels=tuple(args.identity_label),
        )
        evaluate_blind(comparison, evaluator_id=args.evaluator)
        save_blind_review(
            args.output,
            comparison,
            source_digests={result.spec.run_id: digest for result, digest in loaded},
        )
        print("全候補の評価と元結果の対応を保存しました。保存先で確認できます。")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("匿名比較を中断しました。対応表と完了した評価は保存していません。")
        return 2
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print(
            "比較を開始または保存できませんでした。入力証拠・比較条件・保存先を確認してください。"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
