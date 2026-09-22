"""機械判定を変更せず、人間の評価と匿名比較の対応を保持する。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from random import Random

from app.domain.contracts.common import JsonValue, freeze_json, thaw_json

from .contracts import ValidationRunResult, aware, identifier, positive


class RatingState(str, Enum):
    UNRATED = "UNRATED"
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class DimensionRating:
    dimension: str
    state: RatingState

    def __post_init__(self) -> None:
        identifier(self.dimension)
        if not isinstance(self.state, RatingState) or self.state is RatingState.UNRATED:
            raise ValueError("評価入力には確定した評価状態が必要です")


@dataclass(frozen=True)
class HumanEvaluation:
    run_id: str
    evaluator_id: str
    ratings: tuple[DimensionRating, ...]
    comment: str
    rated_at: datetime

    def __post_init__(self) -> None:
        identifier(self.run_id)
        identifier(self.evaluator_id)
        aware(self.rated_at)
        ratings = tuple(self.ratings)
        if not ratings or any(not isinstance(item, DimensionRating) for item in ratings):
            raise ValueError("評価項目が必要です")
        if len({item.dimension for item in ratings}) != len(ratings):
            raise ValueError("評価項目は重複できません")
        if not isinstance(self.comment, str):
            raise ValueError("評価コメントは文字列で指定してください")
        object.__setattr__(self, "ratings", ratings)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "evaluator_id": self.evaluator_id,
            "ratings": [{"dimension": x.dimension, "state": x.state.value} for x in self.ratings],
            "comment": self.comment,
            "rated_at": self.rated_at.isoformat(),
        }


class BlindComparison:
    """登録した実行結果を編集せず、全候補の評価後にだけ対応を開示する。"""

    def __init__(
        self,
        assignment_id: str,
        results: tuple[ValidationRunResult, ...],
        dimensions: tuple[str, ...],
        *,
        seed: int,
        max_candidates: int,
        max_comment_bytes: int,
        identity_labels: tuple[str, ...] = (),
    ) -> None:
        identifier(assignment_id)
        positive(max_candidates)
        positive(max_comment_bytes)
        if type(seed) is not int:
            raise ValueError("比較割当の乱数の種は整数で指定してください")
        if not 2 <= len(results) <= max_candidates:
            raise ValueError("比較には上限以内の複数候補が必要です")
        if len({result.spec.run_id for result in results}) != len(results):
            raise ValueError("比較する実行の識別子は重複できません")
        if not dimensions or len(set(dimensions)) != len(dimensions):
            raise ValueError("比較の評価項目が不正です")
        for dimension in dimensions:
            identifier(dimension)
        baseline = results[0]
        for result in results:
            if (
                result.fixture != baseline.fixture
                or result.spec.mode != baseline.spec.mode
                or result.spec.target_module != baseline.spec.target_module
                or result.spec.target_contract_revision != baseline.spec.target_contract_revision
                or result.spec.repeat_count != baseline.spec.repeat_count
                or result.spec.delay_injections != baseline.spec.delay_injections
                or result.spec.failure_injections != baseline.spec.failure_injections
            ):
                raise ValueError("比較の入力・検証範囲・条件が揃っていません")
            if not result.fixture.human_context or not result.stage_results:
                raise ValueError("入力に由来する説明と実際の出力が必要です")
        shuffled = list(results)
        Random(seed).shuffle(shuffled)
        for label in identity_labels:
            identifier(label)
        self._identity_labels = frozenset(identity_labels) | frozenset(
            label
            for result in results
            for label in (result.spec.run_id, *result.spec.provider_policy_refs)
        )
        self.assignment_id = assignment_id
        self._results = {f"candidate-{index + 1}": result for index, result in enumerate(shuffled)}
        self._dimensions = frozenset(dimensions)
        self._maximum_comment_bytes = max_comment_bytes
        self._ratings: dict[str, HumanEvaluation] = {}

    def view(self) -> JsonValue:
        """実行・モデルのラベルと機械採点を隠し、入力と実出力だけを示す。"""
        view = freeze_json(
            {
                "assignment_id": self.assignment_id,
                "dimensions": sorted(self._dimensions),
                "candidates": [
                    {
                        "label": label,
                        "human_context": result.fixture.human_context,
                        "typed_inputs": result.fixture.typed_inputs,
                        "typed_outputs": [x.typed_outputs for x in result.stage_results],
                        "rating_status": "RECORDED" if label in self._ratings else "UNRATED",
                    }
                    for label, result in self._results.items()
                ],
            }
        )
        encoded = json.dumps(thaw_json(view), ensure_ascii=False)
        if any(label in encoded for label in self._identity_labels):
            raise ValueError("匿名表示の入力または出力に識別情報が含まれています")
        return view

    def record(
        self,
        label: str,
        *,
        evaluator_id: str,
        ratings: tuple[DimensionRating, ...],
        comment: str,
        rated_at: datetime,
    ) -> HumanEvaluation:
        if label not in self._results or label in self._ratings:
            raise ValueError("比較候補が存在しないか、すでに評価されています")
        result = self._results[label]
        record = HumanEvaluation(result.spec.run_id, evaluator_id, ratings, comment, rated_at)
        if {item.dimension for item in record.ratings} != self._dimensions:
            raise ValueError("登録した評価項目すべてへの入力が必要です")
        if len(record.comment.encode("utf-8")) > self._maximum_comment_bytes:
            raise ValueError("評価コメントが容量上限を超えています")
        if record.rated_at < result.completed_at:
            raise ValueError("評価日時は検証完了以降でなければなりません")
        self._ratings[label] = record
        return record

    def reveal(self) -> JsonValue:
        if len(self._ratings) != len(self._results):
            raise ValueError("全候補の評価が完了するまで対応は開示しません")
        return freeze_json(
            {
                "assignment_id": self.assignment_id,
                "candidates": [
                    {
                        "label": label,
                        "run_result": result.to_dict(),
                        "human_evaluation": self._ratings[label].to_dict(),
                    }
                    for label, result in self._results.items()
                ],
            }
        )
