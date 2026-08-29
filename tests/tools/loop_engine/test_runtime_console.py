from __future__ import annotations

import sys
from pathlib import Path

from pytest import CaptureFixture

from tools.loop_engine.runtime_console import RuntimeConsole, VisibleSubprocessLocalRunner


def test_streamed_child_output_is_hidden_by_default_but_persisted(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    console = RuntimeConsole(tmp_path)
    runner = VisibleSubprocessLocalRunner(console)

    result = runner.run(
        (sys.executable, "-c", "print('CHILD_DETAIL')"),
        cwd=tmp_path,
        timeout_seconds=10,
        capture_output=False,
    )

    assert result.succeeded
    stderr = capsys.readouterr().err
    assert "CHILD_DETAIL" not in stderr
    assert "python: 開始" not in stderr
    assert "python: 完了" not in stderr
    log = console.path.read_text(encoding="utf-8")
    assert "CHILD_DETAIL" in log
    assert "python: 開始" in log
    assert "python: 完了" in log


def test_verbose_mode_streams_child_output_and_details(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    console = RuntimeConsole(tmp_path, verbose=True)
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
    assert "python: 開始" in stderr
    assert "python: 完了" in stderr


def test_codex_lifecycle_stays_visible_without_raw_output(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    codex = tmp_path / "codex"
    codex.write_text("#!/bin/sh\necho CODEX_RAW_DETAIL\n", encoding="utf-8")
    codex.chmod(0o755)
    console = RuntimeConsole(tmp_path)
    runner = VisibleSubprocessLocalRunner(console)

    result = runner.run(
        (str(codex),),
        cwd=tmp_path,
        timeout_seconds=10,
        capture_output=False,
    )

    assert result.succeeded
    stderr = capsys.readouterr().err
    assert "codex: 開始" in stderr
    assert "codex: 完了" in stderr
    assert "CODEX_RAW_DETAIL" not in stderr
    assert "CODEX_RAW_DETAIL" in console.path.read_text(encoding="utf-8")


def test_codex_heartbeat_shows_liveness_without_raw_output(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    codex = tmp_path / "codex"
    codex.write_text(
        "#!/bin/sh\necho CODEX_HIDDEN_DETAIL\nsleep 0.2\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    console = RuntimeConsole(tmp_path)
    runner = VisibleSubprocessLocalRunner(console, heartbeat_seconds=0.05)

    result = runner.run(
        (str(codex),),
        cwd=tmp_path,
        timeout_seconds=10,
        capture_output=False,
    )

    assert result.succeeded
    stderr = capsys.readouterr().err
    assert "codex: 実行中" in stderr
    assert "詳細はログを参照" in stderr
    assert "CODEX_HIDDEN_DETAIL" not in stderr
    assert "CODEX_HIDDEN_DETAIL" in console.path.read_text(encoding="utf-8")


def test_codex_is_not_killed_by_generic_wall_clock_timeout(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    codex = tmp_path / "codex"
    codex.write_text(
        "#!/bin/sh\nsleep 0.15\necho CODEX_FINISHED\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    console = RuntimeConsole(tmp_path)
    runner = VisibleSubprocessLocalRunner(console, heartbeat_seconds=0.03)

    result = runner.run(
        (str(codex),),
        cwd=tmp_path,
        timeout_seconds=0,
        capture_output=False,
    )

    assert result.succeeded
    stderr = capsys.readouterr().err
    assert "時間超過" not in stderr
    assert "codex: 実行中" in stderr
    assert "codex: 完了" in stderr
    assert "CODEX_FINISHED" in console.path.read_text(encoding="utf-8")


def test_captured_failure_is_concise_and_full_error_is_persisted(
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
    assert "SAFE_ERROR" not in stderr
    assert "失敗 終了コード=7" in stderr
    assert "詳細ログ:" in stderr
    log = console.path.read_text(encoding="utf-8")
    assert "SAFE_ERROR" in log
    assert secret_like_argument not in stderr
    assert secret_like_argument not in log
