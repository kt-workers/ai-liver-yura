from __future__ import annotations

import sys
from pathlib import Path

from pytest import CaptureFixture

from tools.loop_engine.runtime_console import RuntimeConsole, VisibleSubprocessLocalRunner


def test_streamed_child_output_is_visible_and_persisted(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    console = RuntimeConsole(tmp_path)
    runner = VisibleSubprocessLocalRunner(console)

    result = runner.run(
        (sys.executable, "-c", "print('CHILD_VISIBLE')"),
        cwd=tmp_path,
        timeout_seconds=10,
        capture_output=False,
    )

    assert result.succeeded
    stderr = capsys.readouterr().err
    assert "CHILD_VISIBLE" in stderr
    assert "python: start" in stderr
    assert "python: done" in stderr
    log = console.path.read_text(encoding="utf-8")
    assert "CHILD_VISIBLE" in log
    assert "python: start" in log
    assert "python: done" in log


def test_captured_failure_shows_error_without_exposing_argv(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    console = RuntimeConsole(tmp_path)
    runner = VisibleSubprocessLocalRunner(console)
    secret_like_argument = "DO_NOT_LOG_THIS_ARGUMENT"

    result = runner.run(
        (
            sys.executable,
            "-c",
            "import sys; print('SAFE_ERROR', file=sys.stderr); sys.exit(7)",
            secret_like_argument,
        ),
        cwd=tmp_path,
        timeout_seconds=10,
        capture_output=True,
    )

    assert result.returncode == 7
    stderr = capsys.readouterr().err
    assert "SAFE_ERROR" in stderr
    assert "failed exit=7" in stderr
    assert secret_like_argument not in stderr
    assert secret_like_argument not in console.path.read_text(encoding="utf-8")
