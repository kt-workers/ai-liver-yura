from __future__ import annotations

import selectors
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from .host_runtime import LocalCommandResult


class RuntimeConsole:
    """Writes safe host progress to stderr and a local ignored log file."""

    def __init__(self, root: Path) -> None:
        log_dir = root / "logs" / "loop_engine"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = log_dir / f"loop-engine-{stamp}.log"

    def event(self, message: str) -> None:
        line = f"[loop-engine] {message}"
        print(line, file=sys.stderr, flush=True)
        self._append(line + "\n")

    def child_output(self, text: str) -> None:
        print(text, end="", file=sys.stderr, flush=True)
        self._append(text)

    def _append(self, text: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(text)


class VisibleSubprocessLocalRunner:
    """LocalRunner that exposes long-running child activity without leaking argv."""

    def __init__(self, console: RuntimeConsole) -> None:
        self._console = console

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: int = 120,
        capture_output: bool = True,
    ) -> LocalCommandResult:
        label = _safe_command_label(command)
        self._console.event(f"{label}: start")
        if capture_output:
            return self._run_captured(
                command,
                label=label,
                cwd=cwd,
                environment=environment,
                timeout_seconds=timeout_seconds,
            )
        return self._run_streamed(
            command,
            label=label,
            cwd=cwd,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )

    def _run_captured(
        self,
        command: Sequence[str],
        *,
        label: str,
        cwd: Path | None,
        environment: Mapping[str, str] | None,
        timeout_seconds: int,
    ) -> LocalCommandResult:
        try:
            completed = subprocess.run(
                tuple(command),
                cwd=cwd,
                env=dict(environment) if environment is not None else None,
                check=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            self._console.event(f"{label}: timeout")
            return LocalCommandResult(124)
        except OSError:
            self._console.event(f"{label}: launch failed")
            return LocalCommandResult(127)

        if completed.returncode == 0:
            self._console.event(f"{label}: done")
        else:
            self._console.event(f"{label}: failed exit={completed.returncode}")
            if completed.stderr:
                self._console.child_output(completed.stderr)
        return LocalCommandResult(completed.returncode, completed.stdout or "")

    def _run_streamed(
        self,
        command: Sequence[str],
        *,
        label: str,
        cwd: Path | None,
        environment: Mapping[str, str] | None,
        timeout_seconds: int,
    ) -> LocalCommandResult:
        try:
            process = subprocess.Popen(
                tuple(command),
                cwd=cwd,
                env=dict(environment) if environment is not None else None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError:
            self._console.event(f"{label}: launch failed")
            return LocalCommandResult(127)

        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    process.kill()
                    break
                events = selector.select(timeout=min(0.5, remaining))
                for _key, _ in events:
                    line = process.stdout.readline()
                    if line:
                        self._console.child_output(line)
                if process.poll() is not None:
                    remainder = process.stdout.read()
                    if remainder:
                        self._console.child_output(remainder)
                    break
        finally:
            selector.close()

        if timed_out:
            process.wait()
            self._console.event(f"{label}: timeout")
            return LocalCommandResult(124)
        returncode = process.wait()
        if returncode == 0:
            self._console.event(f"{label}: done")
        else:
            self._console.event(f"{label}: failed exit={returncode}")
        return LocalCommandResult(returncode)


def _safe_command_label(command: Sequence[str]) -> str:
    if not command:
        return "child"
    executable = Path(command[0]).name
    if executable == "codex":
        return "codex"
    if executable == "gh":
        if len(command) > 1 and command[1] == "api":
            return "github observe"
        return "github"
    return executable
