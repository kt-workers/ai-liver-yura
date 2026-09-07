"""人間の評価を機械判定から分離し、比較の出典を保持する検証。"""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.domain.contracts.common import thaw_json
from app.subsystems.validation.evaluation import BlindComparison, DimensionRating, RatingState
from app.subsystems.validation.runtime import ValidationRunner
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, spec, target


async def comparison() -> BlindComparison:
    runner = ValidationRunner((target(),), POLICY)
    results = tuple(
        [await runner.run(replace(spec(), run_id=f"run-{i}"), FIXTURE) for i in range(2)]
    )
    return BlindComparison(
        "comparison", results, ("自然さ",), seed=42, max_candidates=2, max_comment_bytes=100
    )


@pytest.mark.asyncio
async def test_blind_view_keeps_outputs_and_hides_machine_and_model_labels() -> None:
    first, second = await comparison(), await comparison()
    view = str(thaw_json(first.view()))
    assert "machine_gate" not in view and "git_head" not in view
    assert "run-0" not in view and "run-1" not in view
    assert "typed_inputs" in view and "typed_outputs" in view
    assert "入力に由来する説明" in view
    assert first.view() == second.view()
    with pytest.raises(ValueError, match="全候補"):
        first.reveal()


@pytest.mark.asyncio
async def test_human_rejection_never_overrides_machine_pass() -> None:
    assignment = await comparison()
    for label in ("candidate-1", "candidate-2"):
        assignment.record(
            label,
            evaluator_id="試験用評価者",
            ratings=(DimensionRating("自然さ", RatingState.FAIL),),
            comment="試験入力",
            rated_at=datetime.now(timezone.utc),
        )
    revealed = str(thaw_json(assignment.reveal()))
    assert "'machine_gate': 'PASS'" in revealed
    assert "'state': 'FAIL'" in revealed
    assert "run-0" in revealed and "run-1" in revealed
    with pytest.raises(ValueError, match="すでに"):
        assignment.record(
            "candidate-1",
            evaluator_id="試験用評価者",
            ratings=(DimensionRating("自然さ", RatingState.PASS),),
            comment="",
            rated_at=datetime.now(timezone.utc),
        )


@pytest.mark.asyncio
async def test_unmatched_dimensions_do_not_complete_rating() -> None:
    assignment = await comparison()
    with pytest.raises(ValueError, match="評価項目"):
        assignment.record(
            "candidate-1",
            evaluator_id="試験用評価者",
            ratings=(DimensionRating("別項目", RatingState.PASS),),
            comment="",
            rated_at=datetime.now(timezone.utc),
        )
    with pytest.raises(ValueError, match="全候補"):
        assignment.reveal()
