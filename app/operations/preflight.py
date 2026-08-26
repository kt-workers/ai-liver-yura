from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Protocol


class PreflightStatus(str, Enum):
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class CommandResult:
    succeeded: bool


class CommandRunner(Protocol):
    def run(self, command: Sequence[str]) -> CommandResult: ...


class SubprocessCommandRunner:
    """Runs capability probes without retaining or publishing their output."""

    def run(self, command: Sequence[str]) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return CommandResult(False)
        return CommandResult(completed.returncode == 0)


@dataclass(frozen=True, slots=True)
class PreflightResult:
    status: PreflightStatus
    capabilities: Mapping[str, bool]
    blocking_for_loop_bootstrap: tuple[str, ...]
    work_scoped_unavailable: tuple[str, ...]
    diagnostics: tuple[str, ...]

    def as_json(self) -> str:
        payload = asdict(self)
        payload["status"] = self.status.value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class EnvironmentCapabilityPreflight:
    """Secret-safe, read-only capability probes for Loop Engineering."""

    _REPOSITORY = "ktan514/ai-liver-yura"
    _PROJECT_OWNER = "ktan514"
    _PROJECT_NUMBER = "7"

    def __init__(
        self,
        runner: CommandRunner,
        environment: Mapping[str, str] | None = None,
        *,
        verified_project_write: bool = False,
    ) -> None:
        self._runner = runner
        self._environment = environment if environment is not None else os.environ
        self._verified_project_write = verified_project_write

    def run(self) -> PreflightResult:
        probes = {
            "github_cli": ("gh", "auth", "status"),
            "github_repo_read": ("gh", "repo", "view", self._REPOSITORY),
            "github_repo_write": ("git", "push", "--dry-run"),
            "github_project_read": (
                "gh", "project", "view", self._PROJECT_NUMBER, "--owner", self._PROJECT_OWNER
            ),
            "github_project_fields_read": (
                "gh", "project", "field-list", self._PROJECT_NUMBER, "--owner", self._PROJECT_OWNER
            ),
            "github_project_items_read": (
                "gh", "project", "item-list", self._PROJECT_NUMBER, "--owner", self._PROJECT_OWNER
            ),
            "docker": ("docker", "version"),
            "postgresql_client": ("pg_isready", "--version"),
        }
        capability = {name: self._runner.run(command).succeeded for name, command in probes.items()}
        capability["github_project_read"] = all(
            capability.pop(name)
            for name in (
                "github_project_read",
                "github_project_fields_read",
                "github_project_items_read",
            )
        )
        capability["github_project_write"] = self._verified_project_write
        capability["openai_reviewer"] = bool(self._environment.get("OPENAI_API_KEY"))

        blocking = tuple(
            name.upper()
            for name in (
                "github_cli",
                "github_repo_read",
                "github_repo_write",
                "github_project_read",
                "github_project_write",
            )
            if not capability[name]
        )
        scoped = tuple(
            name.upper()
            for name in ("openai_reviewer", "docker", "postgresql_client")
            if not capability[name]
        )
        status = PreflightStatus.BLOCKED if blocking else (
            PreflightStatus.DEGRADED if scoped else PreflightStatus.PASS
        )
        return PreflightResult(status, capability, blocking, scoped, blocking + scoped)


def main() -> None:
    result = EnvironmentCapabilityPreflight(SubprocessCommandRunner()).run()
    print(result.as_json())


if __name__ == "__main__":
    main()
