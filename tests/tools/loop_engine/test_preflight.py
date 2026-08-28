import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from tools.loop_engine.preflight import (
    CommandResult,
    EnvironmentCapabilityPreflight,
    PreflightStatus,
)


class FakeRunner:
    def __init__(
        self,
        failed: tuple[tuple[str, ...], ...] = (),
        *,
        project_write: bool = True,
        repository_write: bool = True,
    ) -> None:
        self.failed = failed
        self.project_write = project_write
        self.repository_write = repository_write
        self.calls: list[tuple[str, ...]] = []
        self.environments: list[Mapping[str, str] | None] = []

    def run(
        self, command: Sequence[str], environment: Mapping[str, str] | None = None
    ) -> CommandResult:
        call = tuple(command)
        self.calls.append(call)
        self.environments.append(environment)
        if call[:3] == ("gh", "api", "graphql"):
            payload = {"data": {"user": {"projectV2": {"viewerCanUpdate": self.project_write}}}}
            return CommandResult(True, json.dumps(payload))
        if call == ("gh", "api", "repos/ktan514/ai-liver-yura"):
            return CommandResult(True, json.dumps({"permissions": {"push": self.repository_write}}))
        return CommandResult(not any(call[: len(prefix)] == prefix for prefix in self.failed))


class FakeReviewer:
    def __init__(self, available: bool) -> None:
        self.available = available
        self.calls: list[str] = []

    def check(self, socket_path: str, timeout_seconds: float) -> bool:
        self.calls.append(socket_path)
        return self.available


def goal_root(tmp_path: Path) -> Path:
    path = tmp_path / "docs" / "operations"
    path.mkdir(parents=True)
    content = b"version: 2\ngeneration: 7\nfull mission\n"
    (path / "loop_mission_goal.md").write_bytes(content)
    return tmp_path


def environment() -> dict[str, str]:
    return {
        "YURA_TRUSTED_REVIEWER_SOCKET": "/private/tmp/yura-reviewer.sock",
        "CODEX_MISSION_GOAL_GENERATION": "7",
        "CODEX_MISSION_GOAL_VERSION": "2",
        "CODEX_MISSION_GOAL_SHA256": hashlib.sha256(
            b"version: 2\ngeneration: 7\nfull mission\n"
        ).hexdigest(),
    }


def test_project_write_is_live_graphql_evidence_not_an_injected_boolean(tmp_path: Path) -> None:
    runner = FakeRunner(project_write=True)
    result = EnvironmentCapabilityPreflight(
        runner, environment(), reviewer_probe=FakeReviewer(True), project_root=goal_root(tmp_path)
    ).run()

    assert result.capabilities["github_project_write"]
    assert any(call[:3] == ("gh", "api", "graphql") for call in runner.calls)
    assert all("item-edit" not in call and "6" not in call for call in runner.calls)


def test_repository_write_uses_fixed_read_only_permission_evidence(tmp_path: Path) -> None:
    runner = FakeRunner(repository_write=True)
    result = EnvironmentCapabilityPreflight(
        runner, environment(), reviewer_probe=FakeReviewer(True), project_root=goal_root(tmp_path)
    ).run()

    assert result.capabilities["github_repo_write"]
    assert ("gh", "api", "repos/ktan514/ai-liver-yura") in runner.calls
    assert ("git", "push", "--dry-run") not in runner.calls
    assert all("6" not in call for call in runner.calls)


def test_repository_write_denial_is_fail_closed(tmp_path: Path) -> None:
    result = EnvironmentCapabilityPreflight(
        FakeRunner(repository_write=False),
        environment(),
        reviewer_probe=FakeReviewer(True),
        project_root=goal_root(tmp_path),
    ).run()

    assert not result.capabilities["github_repo_write"]
    assert "GITHUB_REPO_WRITE" in result.blocking_for_loop_bootstrap


def test_project_write_denial_blocks_without_project_mutation(tmp_path: Path) -> None:
    result = EnvironmentCapabilityPreflight(
        FakeRunner(project_write=False),
        environment(),
        reviewer_probe=FakeReviewer(True),
        project_root=goal_root(tmp_path),
    ).run()

    assert result.status is PreflightStatus.BLOCKED
    assert "GITHUB_PROJECT_WRITE" in result.blocking_for_loop_bootstrap


def test_reviewer_requires_trusted_broker_and_never_receives_reviewer_key(tmp_path: Path) -> None:
    reviewer = FakeReviewer(False)
    env = environment() | {"OPENAI_API_KEY_REVIEWER": "reviewer-secret"}
    result = EnvironmentCapabilityPreflight(
        FakeRunner(), env, reviewer_probe=reviewer, project_root=goal_root(tmp_path)
    ).run()

    assert not result.capabilities["openai_reviewer"]
    assert "OPENAI_REVIEWER" in result.work_scoped_unavailable
    assert reviewer.calls == ["/private/tmp/yura-reviewer.sock"]
    assert "reviewer-secret" not in result.as_json()


def test_postgresql_separates_client_server_database_and_migration(tmp_path: Path) -> None:
    root = goal_root(tmp_path)
    (root / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    env = environment() | {"LOOP_DATABASE_URL": "postgresql://user:password@db.example:5432/loop"}
    runner = FakeRunner((("pg_isready",),))
    result = EnvironmentCapabilityPreflight(
        runner, env, reviewer_probe=FakeReviewer(True), project_root=root
    ).run()

    assert result.capabilities["postgresql_client"]
    assert not result.capabilities["postgresql_server"]
    assert not result.capabilities["postgresql_database"]
    assert not result.capabilities["postgresql_migration"]
    assert "password" not in result.as_json()


def test_goal_generation_mismatch_is_blocking(tmp_path: Path) -> None:
    env = environment() | {"CODEX_MISSION_GOAL_GENERATION": "stale"}
    result = EnvironmentCapabilityPreflight(
        FakeRunner(), env, reviewer_probe=FakeReviewer(True), project_root=goal_root(tmp_path)
    ).run()

    assert "MISSION_GOAL" in result.blocking_for_loop_bootstrap


def test_goal_content_hash_mismatch_is_blocking(tmp_path: Path) -> None:
    env = environment() | {"CODEX_MISSION_GOAL_SHA256": "stale"}
    result = EnvironmentCapabilityPreflight(
        FakeRunner(), env, reviewer_probe=FakeReviewer(True), project_root=goal_root(tmp_path)
    ).run()

    assert "MISSION_GOAL" in result.blocking_for_loop_bootstrap


def test_postgresql_probe_preserves_only_path_and_pg_environment(tmp_path: Path) -> None:
    root = goal_root(tmp_path)
    env = environment() | {
        "PATH": "/opt/homebrew/bin:/usr/bin",
        "LOOP_DATABASE_URL": "postgresql://user:password@db.example/loop",
    }
    runner = FakeRunner()
    EnvironmentCapabilityPreflight(
        runner, env, reviewer_probe=FakeReviewer(True), project_root=root
    ).run()

    database_environment = next(
        environment
        for call, environment in zip(runner.calls, runner.environments, strict=True)
        if call == ("pg_isready",)
    )
    assert database_environment is not None
    assert database_environment["PATH"] == "/opt/homebrew/bin:/usr/bin"
    assert "OPENAI_API_KEY_REVIEWER" not in database_environment


def test_postgresql_malformed_port_fails_closed_and_remains_secret_safe(tmp_path: Path) -> None:
    env = environment() | {
        "LOOP_DATABASE_URL": "postgresql://user:database-secret@db.example:not-a-port/loop"
    }
    result = EnvironmentCapabilityPreflight(
        FakeRunner(), env, reviewer_probe=FakeReviewer(True), project_root=goal_root(tmp_path)
    ).run()

    assert not result.capabilities["postgresql_server"]
    assert not result.capabilities["postgresql_database"]
    assert not result.capabilities["postgresql_migration"]
    assert "database-secret" not in result.as_json()


def test_timeout_becomes_a_typed_diagnostic(tmp_path: Path) -> None:
    class TimeoutRunner(FakeRunner):
        def run(
            self, command: Sequence[str], environment: Mapping[str, str] | None = None
        ) -> CommandResult:
            if tuple(command) == ("docker", "version"):
                return CommandResult(False, timed_out=True)
            return super().run(command, environment)

    result = EnvironmentCapabilityPreflight(
        TimeoutRunner(),
        environment(),
        reviewer_probe=FakeReviewer(True),
        project_root=goal_root(tmp_path),
    ).run()

    assert "DOCKER_TIMEOUT" in result.diagnostics
