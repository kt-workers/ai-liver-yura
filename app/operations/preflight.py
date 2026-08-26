from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit


class PreflightStatus(str, Enum):
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class CommandResult:
    succeeded: bool
    output: str = ""
    timed_out: bool = False


class CommandRunner(Protocol):
    def run(
        self, command: Sequence[str], environment: Mapping[str, str] | None = None
    ) -> CommandResult: ...


class SubprocessCommandRunner:
    """Captures probe output only for local parsing; it is never emitted."""

    _TIMEOUT_SECONDS = 10

    def run(
        self, command: Sequence[str], environment: Mapping[str, str] | None = None
    ) -> CommandResult:
        try:
            result = subprocess.run(
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                env=dict(environment) if environment is not None else None,
                timeout=self._TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(False, timed_out=True)
        except OSError:
            return CommandResult(False)
        return CommandResult(result.returncode == 0, result.stdout)


class ReviewerProbe(Protocol):
    def check(self, api_key: str, model: str, timeout_seconds: float) -> bool: ...


class OpenAIResponsesReviewerProbe:
    """Checks both configured model access and a bounded Responses API request."""

    def check(self, api_key: str, model: str, timeout_seconds: float) -> bool:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=0)
            client.models.retrieve(model)
            client.responses.create(
                model=model, input="preflight health check", max_output_tokens=16
            )
        except Exception:  # Provider errors may carry credential or request details.
            return False
        return True


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
    _REPOSITORY = "ktan514/ai-liver-yura"
    _PROJECT_OWNER = "ktan514"
    _PROJECT_NUMBER = "7"
    _PROJECT_WRITE_QUERY = (
        'query { user(login: "ktan514") { projectV2(number: 7) { viewerCanUpdate } } }'
    )

    def __init__(
        self,
        runner: CommandRunner,
        environment: Mapping[str, str] | None = None,
        *,
        reviewer_probe: ReviewerProbe | None = None,
        project_root: Path | None = None,
    ) -> None:
        self._runner = runner
        self._environment = environment if environment is not None else os.environ
        self._reviewer_probe = reviewer_probe or OpenAIResponsesReviewerProbe()
        self._project_root = project_root or Path.cwd()
        self._timeouts: list[str] = []

    def run(self) -> PreflightResult:
        capability = self._command_capabilities()
        capability["github_project_write"] = self._project_write_allowed()
        capability["mission_goal"] = self._mission_goal_matches()
        capability["project_venv"] = sys.prefix != sys.base_prefix
        capability["openai_reviewer"] = self._reviewer_available()
        capability.update(self._postgresql_capabilities())
        blocking_names = (
            "github_cli",
            "github_repo_read",
            "github_repo_write",
            "github_project_read",
            "github_project_write",
            "mission_goal",
            "project_venv",
            "python",
            "pytest",
            "ruff",
            "mypy",
            "compileall",
            "codex_cli",
        )
        scoped_names = (
            "openai_reviewer",
            "docker",
            "postgresql_client",
            "postgresql_server",
            "postgresql_database",
            "postgresql_migration",
        )
        blocking = tuple(name.upper() for name in blocking_names if not capability[name])
        scoped = tuple(name.upper() for name in scoped_names if not capability[name])
        status = (
            PreflightStatus.BLOCKED
            if blocking
            else PreflightStatus.DEGRADED
            if scoped
            else PreflightStatus.PASS
        )
        return PreflightResult(
            status, capability, blocking, scoped, blocking + scoped + tuple(self._timeouts)
        )

    def _command_capabilities(self) -> dict[str, bool]:
        python = (sys.executable, "--version")
        probes = {
            "github_cli": ("gh", "auth", "status"),
            "github_repo_read": ("gh", "repo", "view", self._REPOSITORY),
            "github_repo_write": ("git", "push", "--dry-run"),
            "github_project_view": ("gh", "project", "view", "7", "--owner", "ktan514"),
            "github_project_fields": ("gh", "project", "field-list", "7", "--owner", "ktan514"),
            "github_project_items": ("gh", "project", "item-list", "7", "--owner", "ktan514"),
            "python": python,
            "pytest": (sys.executable, "-m", "pytest", "--version"),
            "ruff": (sys.executable, "-m", "ruff", "--version"),
            "mypy": (sys.executable, "-m", "mypy", "--version"),
            "compileall": (sys.executable, "-m", "compileall", "--help"),
            "codex_cli": ("codex", "--version"),
            "docker": ("docker", "version"),
            "postgresql_client": ("psql", "--version"),
        }
        capability = {name: self._run(name, command).succeeded for name, command in probes.items()}
        capability["github_project_read"] = all(
            capability.pop(name)
            for name in ("github_project_view", "github_project_fields", "github_project_items")
        )
        return capability

    def _project_write_allowed(self) -> bool:
        result = self._run(
            "github_project_write",
            ("gh", "api", "graphql", "-f", f"query={self._PROJECT_WRITE_QUERY}"),
        )
        try:
            return result.succeeded and bool(
                json.loads(result.output)["data"]["user"]["projectV2"]["viewerCanUpdate"]
            )
        except (KeyError, TypeError, json.JSONDecodeError):
            return False

    def _reviewer_available(self) -> bool:
        key = self._environment.get("OPENAI_API_KEY")
        model = self._reviewer_model()
        return bool(key and model and self._reviewer_probe.check(key, model, 10.0))

    def _postgresql_capabilities(self) -> dict[str, bool]:
        url = self._environment.get("LOOP_DATABASE_URL")
        if not url:
            return {
                "postgresql_server": False,
                "postgresql_database": False,
                "postgresql_migration": False,
            }
        parsed = urlsplit(url)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
            return {
                "postgresql_server": False,
                "postgresql_database": False,
                "postgresql_migration": False,
            }
        database_env = {
            "PATH": self._environment.get("PATH", os.defpath),
            "PGHOST": parsed.hostname,
            "PGPORT": str(parsed.port or 5432),
            "PGUSER": parsed.username or "",
            "PGPASSWORD": parsed.password or "",
            "PGDATABASE": parsed.path.lstrip("/"),
        }
        server = self._run("postgresql_server", ("pg_isready",), database_env).succeeded
        database = (
            server
            and self._run(
                "postgresql_database", ("psql", "-Atqc", "SELECT 1"), database_env
            ).succeeded
        )
        migration = (
            database
            and (self._project_root / "alembic.ini").is_file()
            and self._run(
                "postgresql_migration", (sys.executable, "-m", "alembic", "current"), database_env
            ).succeeded
        )
        return {
            "postgresql_server": server,
            "postgresql_database": database,
            "postgresql_migration": migration,
        }

    def _mission_goal_matches(self) -> bool:
        source = self._project_root / "docs" / "operations" / "loop_mission_goal.md"
        generation = self._environment.get("CODEX_MISSION_GOAL_GENERATION")
        version = self._environment.get("CODEX_MISSION_GOAL_VERSION")
        content_hash = self._environment.get("CODEX_MISSION_GOAL_SHA256")
        if not source.is_file() or not all((generation, version, content_hash)):
            return False
        content = source.read_bytes()
        lines = content.decode("utf-8").splitlines()
        return (
            f"generation: {generation}" in lines
            and f"version: {version}" in lines
            and hashlib.sha256(content).hexdigest() == content_hash
        )

    def _reviewer_model(self) -> str | None:
        config = self._project_root / "docs" / "operations" / "reviewer_config.json"
        try:
            model = json.loads(config.read_text(encoding="utf-8"))["default_model"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            return None
        return model if isinstance(model, str) and model else None

    def _run(
        self, name: str, command: Sequence[str], environment: Mapping[str, str] | None = None
    ) -> CommandResult:
        result = self._runner.run(command, environment)
        if result.timed_out:
            self._timeouts.append(f"{name.upper()}_TIMEOUT")
        return result


def main() -> None:
    print(EnvironmentCapabilityPreflight(SubprocessCommandRunner()).run().as_json())


if __name__ == "__main__":
    main()
