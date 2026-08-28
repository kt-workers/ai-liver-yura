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
            raise AssertionError(f"unexpected command: {args}")
        endpoint = args[2]
        if endpoint not in self._responses:
            raise AssertionError(f"unexpected endpoint: {endpoint}")
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
                    "stack review state only; no explicit current target"
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


def test_471_bootstrap_completion_keeps_integration_issue_open() -> None:
    target = HostTarget(471, True, 477, "b" * 40, False, True, 4, "b" * 40)
    delegate = FakeMissionPort(target)
    port = PilotAwareMissionPort(delegate)

    assert port.complete_work(target)
    assert delegate.close_calls == 0
    assert port.publish_checkpoint("ordinary completion")
    assert delegate.checkpoints
    checkpoint = delegate.checkpoints[-1]
    assert "PILOT_REQUIRED" in checkpoint
    assert "current Work: #471" in checkpoint
    assert "actual V2 Work pilot evidence pending" in checkpoint


def test_default_codex_command_uses_current_exec_contract() -> None:
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
    assert "--full-auto" not in _codex_argv({})


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
    assert command[:8] == _codex_argv({})
    instruction = command[-1]
    assert "actual V2 product pilot" in instruction
    assert "#462/#471自身" in instruction
    assert "loop-engineering基盤責務" in instruction
    assert "dependency-readyなV2 product Work" in instruction


def test_dirty_product_pr_dispatches_reconciliation_without_ready_or_merge() -> None:
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
                    "- next action: fresh Resume Gate / reconcile"
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
    codex_runner = RecordingCodexRunner()
    implementer = PilotPlanningImplementer(
        codex_runner,
        Path("/repo"),
        {"PATH": "/usr/bin"},
        _codex_argv({}),
    )

    result = ReconciliationAwareHostLoopController(mission, implementer).run_once()

    assert result.status is HostTransitionStatus.COMPLETED
    assert result.detail == "MERGE_RECONCILIATION_DISPATCHED"
    assert result.work_issue == 338
    assert result.pr_number == 422
    assert result.head_sha == head
    assert len(codex_runner.commands) == 1
    instruction = codex_runner.commands[0][-1]
    assert "Resume Gate" in instruction
    assert "mergeable_state=dirty" in instruction
    assert "Ready/mergeしない" in instruction
    assert "rebase/force pushは禁止" in instruction


def test_non_integration_work_closes_normally() -> None:
    target = HostTarget(365, True, 500, "c" * 40, False, True, 5, "c" * 40)
    delegate = FakeMissionPort(target)
    port = PilotAwareMissionPort(delegate)

    assert port.complete_work(target)
    assert delegate.close_calls == 1
    assert port.publish_checkpoint("normal checkpoint")
    assert delegate.checkpoints == ["normal checkpoint"]
