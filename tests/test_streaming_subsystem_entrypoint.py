from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from subsystems.streaming.bootstrap.runner import main, run_check

ROOT = Path(__file__).parents[1]


def test_importing_subsystem_has_no_startup_output(capsys: object) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import subsystems.streaming; print('imported')",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0
    assert completed.stdout == "imported\n"
    assert completed.stderr == ""


def test_module_check_mode_succeeds_and_terminates() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "subsystems.streaming", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0
    assert completed.stdout == (
        "streaming-subsystem status=idle healthy=true api_version=1.0\n"
    )
    assert completed.stderr == ""


def test_main_without_mode_prints_help_and_returns(capsys: object) -> None:
    assert main([]) == 0

    captured = capsys.readouterr()
    assert "python -m subsystems.streaming" in captured.out


@pytest.mark.asyncio
async def test_run_check_supports_injected_output() -> None:
    output: list[str] = []

    assert await run_check(output=output.append) == 0
    assert output == [
        "streaming-subsystem status=idle healthy=true api_version=1.0"
    ]
