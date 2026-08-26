import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.operations.preflight import CommandResult, EnvironmentCapabilityPreflight, PreflightStatus


class FakeRunner:
    def __init__(
        self, failed: tuple[tuple[str, ...], ...] = (), *, project_write: bool = True
    ) -> None:
        self.failed = failed
        self.project_write = project_write
        self.calls: list[tuple[str, ...]] = []

    def run(
        self, command: Sequence[str], environment: Mapping[str, str] | None = None
    ) -> CommandResult:
        call = tuple(command)
        self.calls.append(call)
        if call[:3] == ("gh", "api", "graphql"):
            payload = {"data": {"user": {"projectV2": {"viewerCanUpdate": self.project_write}}}}
            return CommandResult(True, json.dumps(payload))
        return CommandResult(not any(call[: len(prefix)] == prefix for prefix in self.failed))


class FakeReviewer:
    def __init__(self, available: bool) -> None:
        self.available = available
        self.calls: list[tuple[str, str]] = []

    def check(self, api_key: str, model: str) -> bool:
        self.calls.append((api_key, model))
        return self.available


def goal_root(tmp_path: Path) -> Path:
    path = tmp_path / "docs" / "operations"
    path.mkdir(parents=True)
    (path / "loop_mission_goal.md").write_text("generation: 7\n", encoding="utf-8")
    return tmp_path


def environment() -> dict[str, str]:
    return {
        "OPENAI_API_KEY": "secret",
        "OPENAI_REVIEWER_MODEL": "reviewer",
        "CODEX_MISSION_GOAL_GENERATION": "7",
    }


def test_project_write_is_live_graphql_evidence_not_an_injected_boolean(tmp_path: Path) -> None:
    runner = FakeRunner(project_write=True)
    result = EnvironmentCapabilityPreflight(
        runner, environment(), reviewer_probe=FakeReviewer(True), project_root=goal_root(tmp_path)
    ).run()

    assert result.capabilities["github_project_write"]
    assert any(call[:3] == ("gh", "api", "graphql") for call in runner.calls)
    assert all("item-edit" not in call and "6" not in call for call in runner.calls)


def test_project_write_denial_blocks_without_project_mutation(tmp_path: Path) -> None:
    result = EnvironmentCapabilityPreflight(
        FakeRunner(project_write=False),
        environment(),
        reviewer_probe=FakeReviewer(True),
        project_root=goal_root(tmp_path),
    ).run()

    assert result.status is PreflightStatus.BLOCKED
    assert "GITHUB_PROJECT_WRITE" in result.blocking_for_loop_bootstrap


def test_reviewer_requires_live_probe_not_just_a_key(tmp_path: Path) -> None:
    reviewer = FakeReviewer(False)
    result = EnvironmentCapabilityPreflight(
        FakeRunner(), environment(), reviewer_probe=reviewer, project_root=goal_root(tmp_path)
    ).run()

    assert not result.capabilities["openai_reviewer"]
    assert "OPENAI_REVIEWER" in result.work_scoped_unavailable
    assert reviewer.calls == [("secret", "reviewer")]
    assert "secret" not in result.as_json()


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
