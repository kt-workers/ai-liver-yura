from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tools.loop_engine.ci_gate import CIGateStatus
from tools.loop_engine.host_entrypoint import (
    PilotAwareMissionPort,
    PilotPlanningImplementer,
    ReconciliationAwareHostLoopController,
    StrictGhMissionPort,
    _codex_argv,
)
from tools.loop_engine.host_runtime import (
    HostLoopController,
    HostTarget,
    HostTransitionStatus,
    LocalCommandResult,
)


class FakeLocalRunner:
    def __init__(self, responses: Mapping[str, object]) -> None:
        self._responses = responses

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: int = 120,
        capture_output: bool = True,
    ) -> LocalCommandResult:
        del cwd, environment, timeout_seconds, capture_output
        args = tuple(command)
        if len(args) < 3 or args[:2] != ("gh", "api"):
            raise AssertionError(f"想定外のコマンドです: {args}")
        endpoint = args[2]
        if endpoint not in self._responses:
            raise AssertionError(f"想定外のGitHub API対象です: {endpoint}")
        return LocalCommandResult(0, json.dumps(self._responses[endpoint]))


class RecordingCodexRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: int = 120,
        capture_output: bool = True,
    ) -> LocalCommandResult:
        del cwd, environment, timeout_seconds, capture_output
        self.commands.append(tuple(command))
        return LocalCommandResult(0, "")


class FakeMissionPort:
    def __init__(self, target: HostTarget) -> None:
        self.target = target
        self.close_calls = 0
        self.checkpoints: list[str] = []

    def current_target(self) -> HostTarget | None:
        return self.target

    def ci_status(self, target: HostTarget) -> CIGateStatus:
        del target
        return CIGateStatus.PASS

    def merge_current(self, target: HostTarget) -> bool:
        del target
        return True

    def complete_work(self, target: HostTarget) -> bool:
        del target
        self.close_calls += 1
        return True

    def publish_checkpoint(self, body: str) -> bool:
        self.checkpoints.append(body)
        return True


class FailingMissionPort:
    def current_target(self) -> HostTarget | None:
        raise RuntimeError("MISSION_CHECKPOINT_TARGET_UNRESOLVED")

    def ci_status(self, target: HostTarget) -> CIGateStatus:
        del target
        return CIGateStatus.PASS

    def merge_current(self, target: HostTarget) -> bool:
        del target
        return False

    def complete_work(self, target: HostTarget) -> bool:
        del target
        return False

    def publish_checkpoint(self, body: str) -> bool:
        del body
        return False


class NoopImplementer:
    def continue_work(self, target: HostTarget, *, repair: bool) -> bool:
        del target, repair
        return False

    def plan_next_work(self, completed_work: int | None) -> bool:
        del completed_work
        return False


class MutablePilotImplementer(PilotPlanningImplementer):
    def __init__(
        self,
        delegate: FakeMissionPort,
        *,
        next_target: HostTarget | None = None,
        advance: bool = True,
    ) -> None:
        self._delegate = delegate
        self._next_target = next_target
        self._advance = advance
        self.plan_calls: list[int | None] = []
        self.continue_calls: list[tuple[int, bool]] = []

    def plan_next_work(self, completed_work: int | None) -> bool:
        self.plan_calls.append(completed_work)
        if self._advance and self._next_target is not None:
            self._delegate.target = self._next_target
        return True

    def continue_work(self, target: HostTarget, *, repair: bool) -> bool:
        self.continue_calls.append((target.work_issue, repair))
        if self._advance and self._next_target is not None:
            self._delegate.target = self._next_target
        return True


def test_latest_ambiguous_mission_checkpoint_does_not_fall_back() -> None:
    responses = {
        "repos/ktan514/ai-liver-yura/issues/450/comments?per_page=100&page=1": [
            {
                "id": 1,
                "body": (
                    "## Mission Checkpoint\n\n"
                    "- current Work: #465\n"
                    "- current PR: #466\n"
                    f"- exact HEAD: `{'1' * 40}`"
                ),
            },
            {
                "id": 2,
                "body": (
                    "## Mission Checkpoint\n\n"
                    "現在対象を明示していない状態記録"
                ),
            },
        ]
    }
    port = StrictGhMissionPort(FakeLocalRunner(responses), {"PATH": "/usr/bin"})

    with pytest.raises(RuntimeError, match="MISSION_CHECKPOINT_TARGET_UNRESOLVED"):
        port.current_target()


def test_latest_explicit_target_is_fresh_read_from_github() -> None:
    head = "a" * 40
    responses = {
        "repos/ktan514/ai-liver-yura/issues/450/comments?per_page=100&page=1": [
            {
                "id": 3,
                "body": (
                    "## Mission Checkpoint\n\n"
                    "- current Work: #471\n"
                    "- current PR: #477\n"
                    f"- exact HEAD: `{head}`"
                ),
            }
        ],
        "repos/ktan514/ai-liver-yura/issues/471": {"state": "open"},
        "repos/ktan514/ai-liver-yura/pulls/477": {
            "head": {"sha": head},
            "merged": False,
            "draft": True,
        },
    }
    port = StrictGhMissionPort(FakeLocalRunner(responses), {"PATH": "/usr/bin"})

    target = port.current_target()

    assert target is not None
    assert target.work_issue == 471
    assert target.pr_number == 477
    assert target.head_sha == head
    assert not target.stale_checkpoint


def test_checkpoint_parse_failure_is_exposed_as_typed_observe_detail() -> None:
    result = HostLoopController(FailingMissionPort(), NoopImplementer()).run_once()

    assert result.status is HostTransitionStatus.INTERVENTION_REQUIRED
    assert result.detail == (
        "GITHUB_OBSERVE_FAILED:MISSION_CHECKPOINT_TARGET_UNRESOLVED"
    )


def test_471_bootstrap_completion_keeps_integration_issue_open() -> None:
    target = HostTarget(471, True, 477, "b" * 40, False, True, 4, "b" * 40)
    delegate = FakeMissionPort(target)
    port = PilotAwareMissionPort(delegate)

    assert port.complete_work(target)
    assert delegate.close_calls == 0
    assert port.publish_checkpoint("通常の完了Checkpoint")
    assert delegate.checkpoints
    checkpoint = delegate.checkpoints[-1]
    assert "実製品試験が必要" in checkpoint
    assert "current Work: #471" in checkpoint
    assert "実製品Workの試験証拠" in checkpoint


def test_default_codex_command_keeps_git_metadata_outside_sandbox() -> None:
    assert _codex_argv({}) == (
        "codex",
        "-a",
        "never",
        "exec",
        "--sandbox",
        "workspace-write",
        "-c",
        "sandbox_workspace_write.network_access=true",
    )
    assert "danger-full-access" not in _codex_argv({})
    assert "--full-auto" not in _codex_argv({})


def test_generic_planning_requires_machine_readable_current_work_field() -> None:
    runner = RecordingCodexRunner()
    implementer = PilotPlanningImplementer(
        runner,
        Path("/repo"),
        {"PATH": "/usr/bin"},
        _codex_argv({}),
    )

    assert implementer.plan_next_work(338)
    assert len(runner.commands) == 1
    instruction = runner.commands[0][-1]
    assert "`- current Work: #<issue>`" in instruction
    assert "`- current PR: #<pr>`" in instruction
    assert "`- exact HEAD: <40-hex-sha>`" in instruction
    assert "別名だけでcurrent Workを代用してはいけません" in instruction


def test_471_planning_excludes_loop_engineering_and_self_from_pilot() -> None:
    runner = RecordingCodexRunner()
    implementer = PilotPlanningImplementer(
        runner,
        Path("/repo"),
        {"PATH": "/usr/bin"},
        _codex_argv({}),
    )

    assert implementer.plan_next_work(471)
    assert len(runner.commands) == 1
    command = runner.commands[0]
    assert command[: len(_codex_argv({}))] == _codex_argv({})
    instruction = command[-1]
    assert "実製品試験対象" in instruction
    assert "#462/#471自身" in instruction
    assert "Loop Engineering基盤責務" in instruction
    assert "依存関係を満たしたV2製品Work" in instruction


def test_471_without_active_pr_routes_to_planning_only() -> None:
    before = HostTarget(471, True, None, None, False, False, 10, None)
    after = HostTarget(340, True, None, None, False, False, 11, None)
    delegate = FakeMissionPort(before)
    mission = PilotAwareMissionPort(delegate)
    implementer = MutablePilotImplementer(delegate, next_target=after)

    result = ReconciliationAwareHostLoopController(mission, implementer).run_once()

    assert result.status is HostTransitionStatus.COMPLETED
    assert result.detail == "PILOT_PLANNING_DISPATCHED"
    assert result.work_issue == 340
    assert implementer.plan_calls == [471]
    assert implementer.continue_calls == []


def test_successful_codex_exit_without_state_progress_is_not_completed() -> None:
    before = HostTarget(340, True, None, None, False, False, 20, None)
    delegate = FakeMissionPort(before)
    mission = PilotAwareMissionPort(delegate)
    implementer = MutablePilotImplementer(delegate, advance=False)

    result = ReconciliationAwareHostLoopController(mission, implementer).run_once()

    assert result.status is HostTransitionStatus.INTERVENTION_REQUIRED
    assert result.detail == "IMPLEMENTER_NO_PROGRESS"
    assert implementer.continue_calls == [(340, False)]


def test_dirty_product_pr_dispatches_reconciliation() -> None:
    head = "d" * 40
    comments_endpoint = (
        "repos/ktan514/ai-liver-yura/issues/450/comments?per_page=100&page=1"
    )
    responses = {
        comments_endpoint: [
            {
                "id": 10,
                "body": (
                    "## Mission Checkpoint — ACTIVE\n\n"
                    "- current Work: #338\n"
                    "- current PR: #422\n"
                    f"- exact HEAD: `{head}`\n"
                    "- next action: 再開確認後に最新基幹へ統合する"
                ),
            }
        ],
        "repos/ktan514/ai-liver-yura/issues/338": {"state": "open"},
        "repos/ktan514/ai-liver-yura/pulls/422": {
            "head": {"sha": head},
            "merged": False,
            "draft": True,
            "mergeable": False,
            "mergeable_state": "dirty",
        },
        f"repos/ktan514/ai-liver-yura/actions/runs?head_sha={head}&per_page=100": {
            "workflow_runs": [
                {
                    "id": 20,
                    "name": "V2 Deterministic CI",
                    "head_sha": head,
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        },
    }
    mission = PilotAwareMissionPort(
        StrictGhMissionPort(FakeLocalRunner(responses), {"PATH": "/usr/bin"})
    )
    delegate = FakeMissionPort(
        HostTarget(338, True, 422, head, True, False, 10, head)
    )
    implementer = MutablePilotImplementer(
        delegate,
        next_target=HostTarget(338, True, 422, "e" * 40, True, False, 11, "e" * 40),
    )

    result = HostLoopController(mission, implementer).run_once()

    assert result.status is HostTransitionStatus.INTERVENTION_REQUIRED
    assert result.detail == "EXPECTED_HEAD_MERGE_FAILED"


def test_non_integration_work_closes_normally() -> None:
    target = HostTarget(365, True, 500, "c" * 40, False, True, 5, "c" * 40)
    delegate = FakeMissionPort(target)
    port = PilotAwareMissionPort(delegate)

    assert port.complete_work(target)
    assert delegate.close_calls == 1
    assert port.publish_checkpoint("通常Checkpoint")
    assert delegate.checkpoints == ["通常Checkpoint"]
