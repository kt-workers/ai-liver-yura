"""Safe actual-host entrypoint layered on the Loop host runtime."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from .host_runtime import (
    CodexImplementer,
    GhMissionPort,
    HostLoopController,
    HostTarget,
    HostTransitionResult,
    LocalRunner,
    MissionPort,
    SubprocessLocalRunner,
    _codex_argv,
    _with_goal_identity,
)
from .preflight import EnvironmentCapabilityPreflight, PreflightStatus, SubprocessCommandRunner

_INTEGRATION_WORK = 471


class StrictGhMissionPort(GhMissionPort):
    """Never falls back from the latest Mission Checkpoint to an older target."""

    def _checkpoint_candidate(self) -> tuple[int, int | None, str | None, int] | None:
        comments = self._issue_comments(450)
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

        work_match = self._CURRENT_WORK_RE.search(body_value) if hasattr(self, "_CURRENT_WORK_RE") else None
        if work_match is None:
            # Regex constants are module-level in host_runtime, so use the same accepted syntax here.
            import re

            work_match = re.search(
                r"(?im)^.*?current\s+Work(?:\s*/\s*Integration)?\s*:\s*`?#?(\d+)",
                body_value,
            )
        if work_match is None:
            raise RuntimeError("MISSION_CHECKPOINT_TARGET_UNRESOLVED")

        import re

        pr_match = re.search(
            r"(?im)^.*?current\s+PR(?:\s*/\s*branch)?\s*:\s*`?#?(\d+)",
            body_value,
        )
        head_match = re.search(
            r"(?im)^.*?(?:exact\s+HEAD|HEAD)\s*:\s*`?([0-9a-f]{40})",
            body_value,
        )
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

    def ci_status(self, target: HostTarget):  # type: ignore[no-untyped-def]
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
        pr_line = f"- current PR: #{target.pr_number}\n" if target.pr_number is not None else ""
        head_line = f"- exact HEAD: `{target.head_sha}`\n" if target.head_sha is not None else ""
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


class ActualHostController(HostLoopController):
    """Named composition boundary for the normal CLI."""


def run_actual_host_transition(
    *,
    root: Path | None = None,
    environment: Mapping[str, str] | None = None,
    local_runner: LocalRunner | None = None,
) -> HostTransitionResult:
    project_root = root or Path(__file__).resolve().parents[2]
    values = _with_goal_identity(project_root, environment or os.environ)
    preflight = EnvironmentCapabilityPreflight(
        SubprocessCommandRunner(), values, project_root=project_root
    ).run()
    if preflight.status is PreflightStatus.BLOCKED:
        from .host_runtime import HostTransitionStatus

        return HostTransitionResult(
            HostTransitionStatus.INTERVENTION_REQUIRED,
            "PREFLIGHT_BLOCKED:" + ",".join(preflight.blocking_for_loop_bootstrap),
        )

    runner = local_runner or SubprocessLocalRunner()
    try:
        argv_prefix = _codex_argv(values)
    except ValueError:
        from .host_runtime import HostTransitionStatus

        return HostTransitionResult(HostTransitionStatus.INTERVENTION_REQUIRED, "CODEX_COMMAND_INVALID")

    mission = PilotAwareMissionPort(StrictGhMissionPort(runner, values))
    implementer = CodexImplementer(runner, project_root, values, argv_prefix)
    return ActualHostController(mission, implementer).run_once()
