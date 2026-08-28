from __future__ import annotations

import subprocess
import sys
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


def test_default_cli_runs_one_actual_host_transition(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    events: list[str] = []
    received: dict[str, object] = {}

    class FakeConsole:
        def __init__(self, root: Path) -> None:
            self.path = root / "logs" / "loop_engine" / "test.log"

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
    monkeypatch.setattr(sys, "argv", ["tools.loop_engine"])

    assert cli.main() == 2
    output = capsys.readouterr().out
    assert '"status": "YIELD_EXTERNAL"' in output
    assert '"detail": "CI_PENDING"' in output
    assert events[0] == "START"
    assert "preflight / GitHub observe: begin" in events
    assert events[-1] == "RESULT status=YIELD_EXTERNAL detail=CI_PENDING"
    assert "root" in received
    assert "local_runner" in received
