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
    """Writes concise progress to stderr and full safe diagnostics to a local log."""

    def __init__(self, root: Path, *, verbose: bool = False) -> None:
        log_dir = root / "logs" / "loop_engine"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = log_dir / f"loop-engine-{stamp}.log"
        self.verbose = verbose

    def event(self, message: str) -> None:
        line = f"[loop-engine] {message}"
        print(line, file=sys.stderr, flush=True)
        self._append(line + "\n")

    def detail(self, message: str) -> None:
        line = f"[loop-engine] {message}"
        if self.verbose:
            print(line, file=sys.stderr, flush=True)
        self._append(line + "\n")

    def child_output(self, text: str) -> None:
        if self.verbose:
            print(text, end="", file=sys.stderr, flush=True)
        self._append(text)

    def _append(self, text: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(text)


class VisibleSubprocessLocalRunner:
    """LocalRunner that keeps routine child traffic in the persistent run log."""

    def __init__(self, console: RuntimeConsole, *, heartbeat_seconds: float = 60.0) -> None:
        self._console = console
        self._heartbeat_seconds = heartbeat_seconds

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
        self._command_event(label, "start")
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

    def _command_event(self, label: str, state: str) -> None:
        message = f"{label}: {state}"
        if label == "codex":
            self._console.event(message)
        else:
            self._console.detail(message)

    def _failure_event(self, label: str, message: str) -> None:
        self._console.event(f"{label}: {message}; see log: {self._console.path}")

    def _heartbeat(self, label: str, elapsed_seconds: float) -> None:
        if label != "codex" or self._console.verbose:
            return
        elapsed = max(1, int(elapsed_seconds))
        self._console.event(f"codex: running ({elapsed}s); details in log")

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
            self._failure_event(label, "timeout")
            return LocalCommandResult(124)
        except OSError:
            self._failure_event(label, "launch failed")
            return LocalCommandResult(127)

        if completed.stderr:
            self._console.child_output(completed.stderr)
        if completed.returncode == 0:
            self._command_event(label, "done")
        else:
            self._failure_event(label, f"failed exit={completed.returncode}")
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
            self._failure_event(label, "launch failed")
            return LocalCommandResult(127)

        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        started = time.monotonic()
        deadline = None if label == "codex" else started + timeout_seconds
        next_heartbeat = started + self._heartbeat_seconds
        timed_out = False
        try:
            while True:
                now = time.monotonic()
                if deadline is not None:
                    remaining = deadline - now
                    if remaining <= 0:
                        timed_out = True
                        process.kill()
                        break
                    select_timeout = min(0.5, remaining)
                else:
                    select_timeout = 0.5
                events = selector.select(timeout=select_timeout)
                for _key, _ in events:
                    line = process.stdout.readline()
                    if line:
                        self._console.child_output(line)
                now = time.monotonic()
                if now >= next_heartbeat:
                    self._heartbeat(label, now - started)
                    next_heartbeat = now + self._heartbeat_seconds
                if process.poll() is not None:
                    remainder = process.stdout.read()
                    if remainder:
                        self._console.child_output(remainder)
                    break
        finally:
            selector.close()

        if timed_out:
            process.wait()
            self._failure_event(label, "timeout")
            return LocalCommandResult(124)
        returncode = process.wait()
        if returncode == 0:
            self._command_event(label, "done")
        else:
            self._failure_event(label, f"failed exit={returncode}")
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
