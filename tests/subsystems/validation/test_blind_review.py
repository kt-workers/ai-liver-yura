"""匿名評価の入力順、途中中断、出典を保持する保存を確認する。"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.subsystems.validation.evaluation import BlindComparison
from app.subsystems.validation.runtime import ValidationRunner
from tests.subsystems.validation.json_values import array_at, value_at
from tests.subsystems.validation.test_evaluation import comparison
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, spec, target
from tools.validation_lab.blind_review import evaluate_blind, save_blind_review


@pytest.mark.asyncio
async def test_all_ratings_precede_reveal_and_export_retains_originals(tmp_path: Path) -> None:
    assignment = await comparison()
    messages: list[str] = []
    answers = iter(["invalid", "2", "試験入力一", "1", "試験入力二"])

    def read(prompt: str) -> str:
        with pytest.raises(ValueError, match="全候補"):
            assignment.reveal()
        displayed = "\n".join(messages)
        assert "run-0" not in displayed and "run-1" not in displayed
        assert "machine_gate" not in displayed and "git_head" not in displayed
        assert displayed.index("入力に由来する状況説明") < displayed.index("実際の出力")
        return next(answers)

    revealed = evaluate_blind(
        assignment, evaluator_id="試験用評価者", read=read, write=messages.append
    )
    save_blind_review(tmp_path / "review", assignment)
    saved = json.loads((tmp_path / "review" / "comparison.json").read_text())
    assert len(array_at(revealed, "candidates")) == 2
    assert {x["run_result"]["run_spec"]["run_id"] for x in saved["comparison"]["candidates"]} == {
        "run-0",
        "run-1",
    }
    assert all(x["run_result"]["machine_gate"] == "PASS" for x in saved["comparison"]["candidates"])
    with pytest.raises(FileExistsError):
        save_blind_review(tmp_path / "review", assignment)


@pytest.mark.asyncio
async def test_interrupted_comparison_does_not_reveal_or_save_and_can_resume(
    tmp_path: Path,
) -> None:
    assignment = await comparison()
    answers = iter(["1", "最初のみ", "q"])
    with pytest.raises(EOFError):
        evaluate_blind(
            assignment,
            evaluator_id="試験用評価者",
            read=lambda _: next(answers),
            write=lambda _: None,
        )
    with pytest.raises(ValueError, match="全候補"):
        save_blind_review(tmp_path / "review", assignment)
    assert not (tmp_path / "review").exists()
    answers = iter(["2", "残り"])
    result = evaluate_blind(
        assignment, evaluator_id="試験用評価者", read=lambda _: next(answers), write=lambda _: None
    )
    assert [value_at(x, "human_evaluation", "comment") for x in array_at(result, "candidates")] == [
        "最初のみ",
        "残り",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["private-model", "run-0"])
async def test_embedded_identity_is_rejected_without_editing_candidates(label: str) -> None:
    fixture = replace(FIXTURE, typed_inputs={"text": f"候補の識別情報: {label}"})
    runner = ValidationRunner((target(),), POLICY)
    results = tuple(
        [await runner.run(replace(spec(), run_id=f"run-{i}"), fixture) for i in range(2)]
    )
    assignment = BlindComparison(
        "comparison",
        results,
        ("自然さ",),
        seed=42,
        max_candidates=2,
        max_comment_bytes=100,
        identity_labels=("private-model",),
    )
    displayed: list[str] = []
    with pytest.raises(ValueError, match="識別情報"):
        evaluate_blind(assignment, evaluator_id="試験用評価者", write=displayed.append)
    assert displayed == []
    assert label in str(results[0].fixture.typed_inputs)
