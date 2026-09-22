"""状況説明を先に示す人間の評価操作と、元の証拠の保全を確認する。"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.subsystems.validation.evaluation import RatingState
from app.subsystems.validation.runtime import ValidationRunner
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, spec, target
from tools.validation_lab.review import evaluate, load_source, save_review


async def source_file(tmp_path: Path) -> Path:
    result = await ValidationRunner((target(),), POLICY).run(spec(), FIXTURE)
    path = tmp_path / "result.json"
    path.write_text(result.export_json(POLICY.max_export_bytes), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_context_precedes_rating_and_export_retains_original_evidence(tmp_path: Path) -> None:
    path = await source_file(tmp_path)
    original = path.read_bytes()
    source, digest = load_source(path)
    displayed: list[str] = []
    answers = iter(["", "2", "試験入力による評価"])

    def read(prompt: str) -> str:
        text = "\n".join(displayed)
        assert "入力に由来する説明" in text and "実際の出力" in text
        assert "machine_gate" not in text and "git_head" not in text
        return next(answers)

    evaluation = evaluate(
        source,
        evaluator_id="試験用評価者",
        dimensions=("見やすさ",),
        read=read,
        write=displayed.append,
    )
    assert evaluation.ratings[0].state is RatingState.FAIL
    output = tmp_path / "review"
    save_review(output, source, digest, evaluation)
    saved = json.loads((output / "review.json").read_text())
    assert saved["run_result"] == json.loads(original)
    assert saved["run_result"]["machine_gate"] == "PASS"
    assert saved["human_evaluation"]["ratings"][0]["state"] == "FAIL"
    assert saved["source_artifact_sha256"] == hashlib.sha256(original).hexdigest()
    assert saved["evaluation_scope"] == "diagnostic_human_review"
    assert path.read_bytes() == original
    markdown = (output / "review.md").read_text()
    assert "試験入力による評価" in markdown
    with pytest.raises(FileExistsError):
        save_review(output, source, digest, evaluation)


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["q\n", ""])
async def test_cli_interruption_creates_no_completed_rating(tmp_path: Path, answer: str) -> None:
    path = await source_file(tmp_path)
    output = tmp_path / "review"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.validation_lab.review",
            str(path),
            "--output",
            str(output),
            "--evaluator",
            "試験用評価者",
            "--dimension",
            "見やすさ",
        ],
        input=answer,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert run.returncode == 2
    assert "中断" in run.stdout
    assert not output.exists()


@pytest.mark.asyncio
async def test_cli_records_only_explicit_inputs(tmp_path: Path) -> None:
    path = await source_file(tmp_path)
    output = tmp_path / "review"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.validation_lab.review",
            str(path),
            "--output",
            str(output),
            "--evaluator",
            "試験用評価者",
            "--dimension",
            "見やすさ",
            "--dimension",
            "状況への適合",
        ],
        input="1\n3\n試験用の明示入力\n",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert run.returncode == 0
    ratings = json.loads((output / "review.json").read_text())["human_evaluation"]["ratings"]
    assert [item["state"] for item in ratings] == ["PASS", "NOT_APPLICABLE"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"human_context": None},
        {"stage_results": []},
        {"status": "PRODUCT_FAILED"},
        {"typed_inputs": {"api_key": "非公開試験値"}},
        {"typed_inputs": float("nan")},
    ],
)
async def test_unusable_evidence_is_rejected_before_display(
    tmp_path: Path, change: dict[str, object]
) -> None:
    path = await source_file(tmp_path)
    payload = json.loads(path.read_text())
    payload.update(change)
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_source(path)


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text('{"status":"COMPLETED","status":"PRODUCT_FAILED"}')
    with pytest.raises(ValueError, match="重複"):
        load_source(path)
