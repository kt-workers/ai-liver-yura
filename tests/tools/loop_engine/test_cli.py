from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from tools.loop_engine import __main__ as cli
from tools.loop_engine.host_runtime import HostTransitionResult, HostTransitionStatus


def test_cli_validates_installation_without_external_mutation() -> None:
    result = subprocess.run(
        (sys.executable, "-m", "tools.loop_engine", "--validate-installation"),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout == "LOOP_ENGINE_INSTALLATION=PASS\n"


def test_once_cli_runs_one_actual_host_transition(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    events: list[str] = []
    received: dict[str, object] = {}

    class FakeConsole:
        def __init__(self, root: Path, *, verbose: bool = False) -> None:
            self.path = root / "logs" / "loop_engine" / "test.log"
            received["verbose"] = verbose

        def event(self, message: str) -> None:
            events.append(message)

    class FakeRunner:
        def __init__(self, console: object) -> None:
            received["console"] = console

    def fake_transition(**kwargs: object) -> HostTransitionResult:
        received.update(kwargs)
        return HostTransitionResult(
            HostTransitionStatus.YIELD_EXTERNAL,
            "CI_PENDING",
            471,
            477,
            "a" * 40,
        )

    monkeypatch.setattr(cli, "RuntimeConsole", FakeConsole)
    monkeypatch.setattr(cli, "VisibleSubprocessLocalRunner", FakeRunner)
    monkeypatch.setattr(
        "tools.loop_engine.host_entrypoint.run_actual_host_transition", fake_transition
    )
    monkeypatch.setattr(sys, "argv", ["tools.loop_engine", "--once"])

    assert cli.main() == 2
    output = capsys.readouterr().out
    assert '"status": "YIELD_EXTERNAL"' in output
    assert '"detail": "CI_PENDING"' in output
    assert received["verbose"] is False
    assert events[0] == "開始 mode=once（1回実行）"
    assert "遷移 1: 開始" in events
    assert events[-1] == "遷移 1: YIELD_EXTERNAL 詳細=CI_PENDING"
    assert "root" in received
    assert "local_runner" in received


def test_default_cli_continues_completed_and_ci_pending_without_operator(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    events: list[str] = []
    sleeps: list[float] = []
    results = iter(
        (
            HostTransitionResult(
                HostTransitionStatus.COMPLETED,
                "IMPLEMENTER_DISPATCHED",
                338,
                422,
                "a" * 40,
            ),
            HostTransitionResult(
                HostTransitionStatus.YIELD_EXTERNAL,
                "CI_PENDING",
                338,
                422,
                "b" * 40,
            ),
            HostTransitionResult(
                HostTransitionStatus.COMPLETED,
                "WORK_MERGED",
                338,
                422,
                "b" * 40,
            ),
            HostTransitionResult(
                HostTransitionStatus.YIELD_EXTERNAL,
                "HUMAN_VERIFICATION_PENDING",
                347,
                455,
                "c" * 40,
            ),
        )
    )

    class FakeConsole:
        def __init__(self, root: Path, *, verbose: bool = False) -> None:
            del verbose
            self.path = root / "test.log"

        def event(self, message: str) -> None:
            events.append(message)

    class FakeRunner:
        def __init__(self, console: object) -> None:
            del console

    def fake_transition(**kwargs: object) -> HostTransitionResult:
        del kwargs
        return next(results)

    monkeypatch.setattr(cli, "RuntimeConsole", FakeConsole)
    monkeypatch.setattr(cli, "VisibleSubprocessLocalRunner", FakeRunner)
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        "tools.loop_engine.host_entrypoint.run_actual_host_transition", fake_transition
    )
    monkeypatch.setattr(sys, "argv", ["tools.loop_engine"])

    assert cli.main() == 2
    output = capsys.readouterr().out
    assert output.count("\n") == 1
    assert '"detail": "HUMAN_VERIFICATION_PENDING"' in output
    assert sleeps == [60.0]
    assert events[0] == "開始 mode=continuous（継続実行）"
    assert events.count("継続: 現在状態を再観測します") == 2
    assert "CI待機: 60秒後に自動再開します" in events
    assert "遷移 4: YIELD_EXTERNAL 詳細=HUMAN_VERIFICATION_PENDING" in events


def test_continuous_cli_stops_repeated_completed_no_progress(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    calls = 0

    class FakeConsole:
        def __init__(self, root: Path, *, verbose: bool = False) -> None:
            del verbose
            self.path = root / "test.log"

        def event(self, message: str) -> None:
            del message

    class FakeRunner:
        def __init__(self, console: object) -> None:
            del console

    def fake_transition(**kwargs: object) -> HostTransitionResult:
        nonlocal calls
        del kwargs
        calls += 1
        return HostTransitionResult(
            HostTransitionStatus.COMPLETED,
            "IMPLEMENTER_DISPATCHED",
            338,
            422,
            "a" * 40,
        )

    monkeypatch.setattr(cli, "RuntimeConsole", FakeConsole)
    monkeypatch.setattr(cli, "VisibleSubprocessLocalRunner", FakeRunner)
    monkeypatch.setattr(
        "tools.loop_engine.host_entrypoint.run_actual_host_transition", fake_transition
    )
    monkeypatch.setattr(sys, "argv", ["tools.loop_engine"])

    assert cli.main() == 3
    assert calls == 3
    output = capsys.readouterr().out
    assert '"detail": "NO_PROGRESS_GUARD"' in output


def test_verbose_flag_reaches_runtime_console(monkeypatch: MonkeyPatch) -> None:
    received: dict[str, object] = {}

    class FakeConsole:
        def __init__(self, root: Path, *, verbose: bool = False) -> None:
            self.path = root / "test.log"
            received["verbose"] = verbose

        def event(self, message: str) -> None:
            del message

    class FakeRunner:
        def __init__(self, console: object) -> None:
            del console

    def fake_transition(**kwargs: object) -> HostTransitionResult:
        del kwargs
        return HostTransitionResult(HostTransitionStatus.COMPLETED, "DONE")

    monkeypatch.setattr(cli, "RuntimeConsole", FakeConsole)
    monkeypatch.setattr(cli, "VisibleSubprocessLocalRunner", FakeRunner)
    monkeypatch.setattr(
        "tools.loop_engine.host_entrypoint.run_actual_host_transition", fake_transition
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["tools.loop_engine", "--once", "--verbose"],
    )

    assert cli.main() == 0
    assert received["verbose"] is True
