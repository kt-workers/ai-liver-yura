import json
from collections.abc import Sequence

from app.operations.preflight import (
    CommandResult,
    EnvironmentCapabilityPreflight,
    PreflightStatus,
)


class FakeRunner:
    def __init__(self, failed_prefixes: tuple[tuple[str, ...], ...] = ()) -> None:
        self.failed_prefixes = failed_prefixes
        self.calls: list[tuple[str, ...]] = []

    def run(self, command: Sequence[str]) -> CommandResult:
        normalized = tuple(command)
        self.calls.append(normalized)
        failed = any(
            normalized[: len(prefix)] == prefix for prefix in self.failed_prefixes
        )
        return CommandResult(not failed)


def test_passes_with_live_project_write_evidence_and_never_addresses_project_six() -> None:
    runner = FakeRunner()
    result = EnvironmentCapabilityPreflight(
        runner, {"OPENAI_API_KEY": "not-emitted"}, verified_project_write=True
    ).run()

    assert result.status is PreflightStatus.PASS
    assert all(result.capabilities.values())
    assert all("6" not in command for command in runner.calls)
    assert "not-emitted" not in result.as_json()


def test_missing_project_read_is_bootstrap_blocker() -> None:
    result = EnvironmentCapabilityPreflight(
        FakeRunner((("gh", "project", "field-list"),)),
        {"OPENAI_API_KEY": "present"},
        verified_project_write=True,
    ).run()

    assert result.status is PreflightStatus.BLOCKED
    assert "GITHUB_PROJECT_READ" in result.blocking_for_loop_bootstrap


def test_every_invocation_rechecks_all_project_seven_reads_without_mutation() -> None:
    runner = FakeRunner()
    preflight = EnvironmentCapabilityPreflight(
        runner, {"OPENAI_API_KEY": "present"}, verified_project_write=True
    )

    preflight.run()
    preflight.run()

    project_commands = [call for call in runner.calls if call[:2] == ("gh", "project")]
    assert project_commands == [
        ("gh", "project", "view", "7", "--owner", "ktan514"),
        ("gh", "project", "field-list", "7", "--owner", "ktan514"),
        ("gh", "project", "item-list", "7", "--owner", "ktan514"),
    ] * 2
    assert all("item-edit" not in command and "6" not in command for command in project_commands)


def test_missing_reviewer_is_work_scoped_and_secret_is_not_serialized() -> None:
    result = EnvironmentCapabilityPreflight(FakeRunner(), {}, verified_project_write=True).run()
    serialized = json.loads(result.as_json())

    assert result.status is PreflightStatus.DEGRADED
    assert result.blocking_for_loop_bootstrap == ()
    assert serialized["work_scoped_unavailable"] == ["OPENAI_REVIEWER"]


def test_repo_write_failure_is_bootstrap_blocker() -> None:
    result = EnvironmentCapabilityPreflight(
        FakeRunner((("git", "push", "--dry-run"),)),
        {"OPENAI_API_KEY": "present"},
        verified_project_write=True,
    ).run()

    assert result.status is PreflightStatus.BLOCKED
    assert "GITHUB_REPO_WRITE" in result.diagnostics
