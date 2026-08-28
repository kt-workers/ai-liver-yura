"""Safe actual-host entrypoint layered on the Loop host runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .ci_gate import CIGateStatus
from .host_runtime import (
    CodexImplementer,
    GhMissionPort,
    HostLoopController,
    HostTarget,
    HostTransitionResult,
    HostTransitionStatus,
    LocalRunner,
    MissionPort,
    SubprocessLocalRunner,
)
from .preflight import (
    EnvironmentCapabilityPreflight,
    PreflightStatus,
    SubprocessCommandRunner,
)

_INTEGRATION_WORK = 471
_MISSION_ISSUE = 450
_CURRENT_WORK_RE = re.compile(
    r"(?im)^.*?current\s+Work(?:\s*/\s*Integration)?\s*:\s*`?#?(\d+)"
)
_CURRENT_PR_RE = re.compile(
    r"(?im)^.*?current\s+PR(?:\s*/\s*branch)?\s*:\s*`?#?(\d+)"
)
_EXACT_HEAD_RE = re.compile(
    r"(?im)^.*?(?:exact\s+HEAD|HEAD)\s*:\s*`?([0-9a-f]{40})"
)


class StrictGhMissionPort(GhMissionPort):
    """Never falls back from the latest Mission Checkpoint to an older target."""

    def _checkpoint_candidate(self) -> tuple[int, int | None, str | None, int] | None:
        comments = self._issue_comments(_MISSION_ISSUE)
        latest_checkpoint: dict[str, object] | None = None
        for comment in reversed(comments):
            body = comment.get("body")
            if isinstance(body, str) and "Mission Checkpoint" in body:
                latest_checkpoint = comment
                break
        if latest_checkpoint is None:
            return None

        body_value = latest_checkpoint.get("body")
        if not isinstance(body_value, str):
            raise RuntimeError("MISSION_CHECKPOINT_TARGET_UNRESOLVED")
        work_match = _CURRENT_WORK_RE.search(body_value)
        if work_match is None:
            raise RuntimeError("MISSION_CHECKPOINT_TARGET_UNRESOLVED")

        pr_match = _CURRENT_PR_RE.search(body_value)
        head_match = _EXACT_HEAD_RE.search(body_value)
        comment_id = latest_checkpoint.get("id")
        if not isinstance(comment_id, int):
            raise RuntimeError("MISSION_CHECKPOINT_TARGET_UNRESOLVED")
        return (
            int(work_match.group(1)),
            int(pr_match.group(1)) if pr_match else None,
            head_match.group(1) if head_match else None,
            comment_id,
        )


class PilotAwareMissionPort(MissionPort):
    """Keeps #471 open after its bootstrap PR until an actual V2 pilot completes."""

    def __init__(self, delegate: MissionPort) -> None:
        self._delegate = delegate
        self._bootstrap_target: HostTarget | None = None

    def current_target(self) -> HostTarget | None:
        return self._delegate.current_target()

    def ci_status(self, target: HostTarget) -> CIGateStatus:
        return self._delegate.ci_status(target)

    def merge_current(self, target: HostTarget) -> bool:
        return self._delegate.merge_current(target)

    def complete_work(self, target: HostTarget) -> bool:
        if target.work_issue == _INTEGRATION_WORK:
            self._bootstrap_target = target
            return True
        return self._delegate.complete_work(target)

    def publish_checkpoint(self, body: str) -> bool:
        target = self._bootstrap_target
        if target is None:
            return self._delegate.publish_checkpoint(body)
        pr_line = (
            f"- current PR: #{target.pr_number}\n" if target.pr_number is not None else ""
        )
        head_line = (
            f"- exact HEAD: `{target.head_sha}`\n" if target.head_sha is not None else ""
        )
        checkpoint = (
            "## Mission Checkpoint — ACTIVE / PILOT_REQUIRED\n\n"
            "- Mission state: `ACTIVE`\n"
            f"- current Work: #{target.work_issue}\n"
            f"{pr_line}"
            f"{head_line}"
            "- #477 bootstrap: merged/readback completed\n"
            "- #471 state: open; actual V2 Work pilot evidence pending\n"
            "- next action: Project #7とGitHub liveからactual V2 pilot Workを1件fresh選択する\n"
            "- review policy: non-functional findings / `NOT_RUN` are non-blocking"
        )
        return self._delegate.publish_checkpoint(checkpoint)


def run_actual_host_transition(
    *,
    root: Path | None = None,
    environment: Mapping[str, str] | None = None,
    local_runner: LocalRunner | None = None,
) -> HostTransitionResult:
    project_root = root or Path(__file__).resolve().parents[2]
    values = _canonical_goal_environment(project_root, environment or os.environ)
    preflight = EnvironmentCapabilityPreflight(
        SubprocessCommandRunner(), values, project_root=project_root
    ).run()
    if preflight.status is PreflightStatus.BLOCKED:
        return HostTransitionResult(
            HostTransitionStatus.INTERVENTION_REQUIRED,
            "PREFLIGHT_BLOCKED:" + ",".join(preflight.blocking_for_loop_bootstrap),
        )

    runner = local_runner or SubprocessLocalRunner()
    try:
        argv_prefix = _codex_argv(values)
    except ValueError:
        return HostTransitionResult(
            HostTransitionStatus.INTERVENTION_REQUIRED,
            "CODEX_COMMAND_INVALID",
        )

    mission = PilotAwareMissionPort(StrictGhMissionPort(runner, values))
    implementer = CodexImplementer(runner, project_root, values, argv_prefix)
    return HostLoopController(mission, implementer).run_once()


def _canonical_goal_environment(
    root: Path, environment: Mapping[str, str]
) -> dict[str, str]:
    values = dict(environment)
    goal = root / "docs" / "operations" / "loop_mission_goal.md"
    if not goal.is_file():
        return values
    content = goal.read_bytes()
    lines = content.decode("utf-8").splitlines()
    version = next(
        (line.removeprefix("version: ") for line in lines if line.startswith("version: ")),
        "",
    )
    generation = next(
        (
            line.removeprefix("generation: ")
            for line in lines
            if line.startswith("generation: ")
        ),
        "",
    )
    values["CODEX_MISSION_GOAL_VERSION"] = version
    values["CODEX_MISSION_GOAL_GENERATION"] = generation
    values["CODEX_MISSION_GOAL_SHA256"] = hashlib.sha256(content).hexdigest()
    return values


def _codex_argv(environment: Mapping[str, str]) -> tuple[str, ...]:
    configured = environment.get("LOOP_CODEX_COMMAND_JSON")
    if not configured:
        return ("codex", "exec", "--full-auto")
    try:
        payload = json.loads(configured)
    except json.JSONDecodeError as error:
        raise ValueError("invalid Codex command") from error
    if not isinstance(payload, list) or not payload or not all(
        isinstance(item, str) and item for item in payload
    ):
        raise ValueError("invalid Codex command")
    return tuple(cast(list[str], payload))
