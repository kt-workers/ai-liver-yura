"""保存済みの実行証拠から匿名比較を開始し、出典を保持する操作を確認する。"""

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.subsystems.validation.contracts import DelayInjection
from app.subsystems.validation.runtime import ValidationRunner
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, spec, target
from tools.validation_lab.result_source import load_result


async def sources(tmp_path: Path) -> list[Path]:
    runner = ValidationRunner((target(),), POLICY)
    paths = []
    for index in range(2):
        result = await runner.run(replace(spec(), run_id=f"private-run-{index}"), FIXTURE)
        path = tmp_path / f"source-{index}.json"
        path.write_text(result.export_json(POLICY.max_export_bytes))
        paths.append(path)
    return paths


def command(paths: list[Path], output: Path, answers: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.validation_lab.blind_review",
            *map(str, paths),
            "--output",
            str(output),
            "--assignment",
            "比較試験",
            "--seed",
            "42",
            "--evaluator",
            "試験用評価者",
            "--dimension",
            "自然さ",
        ],
        input=answers,
        text=True,
        capture_output=True,
        timeout=5,
    )


@pytest.mark.asyncio
async def test_command_preserves_exact_sources_and_only_saves_after_all_ratings(
    tmp_path: Path,
) -> None:
    paths = await sources(tmp_path)
    originals = [path.read_bytes() for path in paths]
    output = tmp_path / "review"
    result = command(paths, output, "2\n試験入力一\n1\n試験入力二\n")
    assert result.returncode == 0, result.stderr
    assert "private-run" not in result.stdout and "git_head" not in result.stdout
    saved = json.loads((output / "comparison.json").read_text())
    candidates = {
        x["run_result"]["run_spec"]["run_id"]: x for x in saved["comparison"]["candidates"]
    }
    for original, path in zip(originals, paths, strict=True):
        payload = json.loads(original)
        run_id = payload["run_spec"]["run_id"]
        assert candidates[run_id]["run_result"] == payload
        assert saved["source_artifact_sha256"][run_id] == hashlib.sha256(original).hexdigest()
        assert path.read_bytes() == original
    before = (output / "comparison.json").read_bytes()
    assert command(paths, output, "").returncode == 1
    assert (output / "comparison.json").read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["q\n", "1\n最初だけ\n"])
async def test_command_interruption_never_writes_mapping(tmp_path: Path, answer: str) -> None:
    paths = await sources(tmp_path)
    output = tmp_path / "review"
    result = command(paths, output, answer)
    assert result.returncode == 2 and not output.exists()
    assert "private-run" not in result.stdout


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unknown", "rating", "integer", "timeline"])
async def test_source_rejects_lossy_or_invalid_restoration(tmp_path: Path, change: str) -> None:
    path = (await sources(tmp_path))[0]
    payload = json.loads(path.read_text())
    if change == "unknown":
        payload["unrecognized_evidence"] = "保持すべき追加証拠"
    elif change == "rating":
        payload["human_evaluation"] = {"status": "PASS"}
    elif change == "integer":
        payload["run_spec"]["repeat_count"] = True
    else:
        payload["timeline"][0]["completed_ns"] = -1
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_result(path)


@pytest.mark.asyncio
async def test_restoration_keeps_injection_and_diagnostic_evidence(tmp_path: Path) -> None:
    result = await ValidationRunner((target(),), POLICY).run(spec(), FIXTURE)
    result = replace(
        result,
        spec=replace(result.spec, delay_injections=(DelayInjection("provider", 0.25, 2),)),
        provider_diagnostics=({"elapsed_ns": 17},),
        diagnostics_dropped=3,
    )
    path = tmp_path / "source.json"
    path.write_text(result.export_json(POLICY.max_export_bytes))
    restored, _ = load_result(path)
    assert restored.to_dict() == result.to_dict()
