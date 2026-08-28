"""ai-liver-yura host composition for one bounded Loop Engineering transition.

The deterministic domain remains in the other ``tools.loop_engine`` modules.  This
module binds the current Mission checkpoint to fresh GitHub readback, Codex, CI,
and the normal expected-head merge path so the CLI can make real progress without
copying TaskPackets between humans and agents.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, cast

from .ci_gate import CIGateStatus, CIObservation, evaluate_exact_head
from .preflight import EnvironmentCapabilityPreflight, PreflightStatus, SubprocessCommandRunner

_REPOSITORY = "ktan514/ai-liver-yura"
_OWNER = "ktan514"
_PROJECT_NUMBER = 7
_MISSION_ISSUE = 450
_ROOT_ISSUE = 317
_PARENT_ISSUE = 462
_TRUNK = "rebuild/v2-foundation"
_CI_WORKFLOW_NAME = "V2 Deterministic CI"
_SAFE_OBSERVE_FAILURES = frozenset(
    {
        "MISSION_CHECKPOINT_TARGET_UNRESOLVED",
        "GitHub comments response is not a list",
        "GitHub API response is not an object",
        "GitHub API unavailable",
        "GitHub API returned invalid JSON",
    }
)

_CURRENT_WORK_RE = re.compile(r"(?im)^.*?current\s+Work(?:\s*/\s*Integration)?\s*:\s*`?#?(\d+)")
_CURRENT_PR_RE = re.compile(r"(?im)^.*?current\s+PR(?:\s*/\s*branch)?\s*:\s*`?#?(\d+)")
_EXACT_HEAD_RE = re.compile(r"(?im)^.*?(?:exact\s+HEAD|HEAD)\s*:\s*`?([0-9a-f]{40})")


class HostTransitionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    YIELD_EXTERNAL = "YIELD_EXTERNAL"
    INTERVENTION_REQUIRED = "INTERVENTION_REQUIRED"


@dataclass(frozen=True, slots=True)
class HostTarget:
    work_issue: int
    issue_open: bool
    pr_number: int | None
    head_sha: str | None
    draft: bool
    merged: bool
    checkpoint_comment_id: int
    checkpoint_head_sha: str | None
    stale_checkpoint: bool = False


@dataclass(frozen=True, slots=True)
class HostTransitionResult:
    status: HostTransitionStatus
    detail: str
    work_issue: int | None = None
    pr_number: int | None = None
    head_sha: str | None = None

    def as_json(self) -> str:
        payload = asdict(self)
        payload["status"] = self.status.value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class LocalCommandResult:
    returncode: int
    output: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


class LocalRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: int = 120,
        capture_output: bool = True,
    ) -> LocalCommandResult: ...


class SubprocessLocalRunner:
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: int = 120,
        capture_output: bool = True,
    ) -> LocalCommandResult:
        try:
            completed = subprocess.run(
                tuple(command),
                cwd=cwd,
                env=dict(environment) if environment is not None else None,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired):
            return LocalCommandResult(127)
        return LocalCommandResult(completed.returncode, completed.stdout or "")


class MissionPort(Protocol):
    def current_target(self) -> HostTarget | None: ...

    def ci_status(self, target: HostTarget) -> CIGateStatus: ...

    def merge_current(self, target: HostTarget) -> bool: ...

    def complete_work(self, target: HostTarget) -> bool: ...

    def publish_checkpoint(self, body: str) -> bool: ...


class ImplementerPort(Protocol):
    def continue_work(self, target: HostTarget, *, repair: bool) -> bool: ...

    def plan_next_work(self, completed_work: int | None) -> bool: ...


class GhMissionPort:
    """Trusted-host GitHub adapter. Checkpoint values are candidates, never authority."""

    def __init__(self, runner: LocalRunner, environment: Mapping[str, str]) -> None:
        self._runner = runner
        self._environment = _github_environment(environment)

    def current_target(self) -> HostTarget | None:
        candidate = self._checkpoint_candidate()
        if candidate is None:
            return None
        work_issue, pr_number, checkpoint_head, comment_id = candidate
        issue = self._api_json(f"repos/{_REPOSITORY}/issues/{work_issue}")
        issue_open = _string(issue.get("state")) == "open"
        if pr_number is None:
            return HostTarget(
                work_issue,
                issue_open,
                None,
                None,
                False,
                False,
                comment_id,
                checkpoint_head,
                checkpoint_head is not None,
            )
        pull = self._api_json(f"repos/{_REPOSITORY}/pulls/{pr_number}")
        head = _nested_string(pull, "head", "sha")
        merged = bool(pull.get("merged"))
        draft = bool(pull.get("draft"))
        stale = bool(checkpoint_head and head and checkpoint_head != head)
        return HostTarget(
            work_issue,
            issue_open,
            pr_number,
            head,
            draft,
            merged,
            comment_id,
            checkpoint_head,
            stale,
        )

    def ci_status(self, target: HostTarget) -> CIGateStatus:
        if target.head_sha is None:
            return CIGateStatus.STALE
        response = self._api_json(
            f"repos/{_REPOSITORY}/actions/runs?head_sha={target.head_sha}&per_page=100"
        )
        runs = response.get("workflow_runs")
        if not isinstance(runs, list):
            return CIGateStatus.YIELD_EXTERNAL
        matching: list[dict[str, object]] = []
        for raw in runs:
            if not isinstance(raw, dict):
                continue
            run = cast(dict[str, object], raw)
            if _string(run.get("name")) != _CI_WORKFLOW_NAME:
                continue
            if _string(run.get("head_sha")) != target.head_sha:
                continue
            matching.append(run)
        if not matching:
            return CIGateStatus.YIELD_EXTERNAL
        latest = max(matching, key=lambda item: _integer(item.get("id")))
        conclusion = _string(latest.get("conclusion"))
        status = _string(latest.get("status"))
        if status != "completed":
            conclusion = None
        return evaluate_exact_head(target.head_sha, CIObservation(target.head_sha, conclusion))

    def merge_current(self, target: HostTarget) -> bool:
        if target.pr_number is None or target.head_sha is None:
            return False
        fresh = self.current_target()
        if fresh is None or fresh.pr_number != target.pr_number or fresh.head_sha != target.head_sha:
            return False
        if fresh.stale_checkpoint:
            return False
        if fresh.merged:
            return True
        if fresh.draft:
            ready = self._run_gh(("pr", "ready", str(target.pr_number), "--repo", _REPOSITORY))
            if not ready.succeeded:
                return False
            fresh = self.current_target()
            if fresh is None or fresh.head_sha != target.head_sha:
                return False
        merged = self._run_gh(
            (
                "pr",
                "merge",
                str(target.pr_number),
                "--repo",
                _REPOSITORY,
                "--merge",
                "--match-head-commit",
                target.head_sha,
            ),
            timeout_seconds=180,
        )
        if not merged.succeeded:
            return False
        readback = self._api_json(f"repos/{_REPOSITORY}/pulls/{target.pr_number}")
        return bool(readback.get("merged"))

    def complete_work(self, target: HostTarget) -> bool:
        issue = self._api_json(f"repos/{_REPOSITORY}/issues/{target.work_issue}")
        if _string(issue.get("state")) == "closed":
            return True
        result = self._run_gh(
            ("issue", "close", str(target.work_issue), "--repo", _REPOSITORY, "--reason", "completed")
        )
        if not result.succeeded:
            return False
        readback = self._api_json(f"repos/{_REPOSITORY}/issues/{target.work_issue}")
        return _string(readback.get("state")) == "closed"

    def publish_checkpoint(self, body: str) -> bool:
        result = self._run_gh(
            (
                "api",
                f"repos/{_REPOSITORY}/issues/{_MISSION_ISSUE}/comments",
                "-f",
                f"body={body}",
            )
        )
        return result.succeeded

    def _checkpoint_candidate(self) -> tuple[int, int | None, str | None, int] | None:
        comments = self._issue_comments(_MISSION_ISSUE)
        for comment in reversed(comments):
            body = _string(comment.get("body"))
            if "Mission Checkpoint" not in body:
                continue
            work_match = _CURRENT_WORK_RE.search(body)
            if work_match is None:
                continue
            pr_match = _CURRENT_PR_RE.search(body)
            head_match = _EXACT_HEAD_RE.search(body)
            return (
                int(work_match.group(1)),
                int(pr_match.group(1)) if pr_match else None,
                head_match.group(1) if head_match else None,
                _integer(comment.get("id")),
            )
        return None

    def _issue_comments(self, issue_number: int) -> list[dict[str, object]]:
        comments: list[dict[str, object]] = []
        for page in range(1, 21):
            raw = self._api_value(
                f"repos/{_REPOSITORY}/issues/{issue_number}/comments?per_page=100&page={page}"
            )
            if not isinstance(raw, list):
                raise RuntimeError("GitHub comments response is not a list")
            page_items: list[dict[str, object]] = []
            for item in raw:
                if isinstance(item, dict):
                    page_items.append(cast(dict[str, object], item))
            comments.extend(page_items)
            if len(raw) < 100:
                break
        return comments

    def _api_json(self, endpoint: str) -> dict[str, object]:
        raw = self._api_value(endpoint)
        if not isinstance(raw, dict):
            raise RuntimeError("GitHub API response is not an object")
        return cast(dict[str, object], raw)

    def _api_value(self, endpoint: str) -> object:
        result = self._run_gh(("api", endpoint))
        if not result.succeeded:
            raise RuntimeError("GitHub API unavailable")
        try:
            return json.loads(result.output)
        except json.JSONDecodeError as error:
            raise RuntimeError("GitHub API returned invalid JSON") from error

    def _run_gh(
        self, arguments: Sequence[str], *, timeout_seconds: int = 60
    ) -> LocalCommandResult:
        return self._runner.run(
            ("gh", *arguments), environment=self._environment, timeout_seconds=timeout_seconds
        )


class CodexImplementer:
    def __init__(
        self,
        runner: LocalRunner,
        root: Path,
        environment: Mapping[str, str],
        argv_prefix: Sequence[str],
    ) -> None:
        self._runner = runner
        self._root = root
        self._environment = _codex_environment(environment)
        self._argv_prefix = tuple(argv_prefix)

    def continue_work(self, target: HostTarget, *, repair: bool) -> bool:
        mode = "functional CI repair" if repair else "implementation continuation"
        pr_text = f"PR #{target.pr_number}" if target.pr_number is not None else "current Work lineage"
        instruction = (
            f"Mission #450 / Parent #462 の current Work #{target.work_issue} ({pr_text}) を、"
            f"{mode}として1 bounded transitionだけ進めてください。GitHub live stateとRepository canonicalをfresh readし、"
            "設計→コード→テストの順序を守り、実際に動かないfunctional blockerだけを修正必須としてください。"
            "canonical reviewの非機能findingやprovider NOT_RUNを理由に停止・reviewer hardeningしないでください。"
            "normal push後はexact HEADをfresh readbackし、#450へ日本語のMission Checkpointを1回記録してください。"
            "force push/rebase、Project #6 mutation、reviewer credential利用は禁止です。"
        )
        return self._run_codex(instruction)

    def plan_next_work(self, completed_work: int | None) -> bool:
        completed = f"#{completed_work}" if completed_work is not None else "current Work未解決"
        instruction = (
            f"Mission #450のplanning-only transitionです。直前Workは{completed}です。"
            "#207/#317/#450/#462、Project #7、GitHub live Issue/PRをfresh readし、"
            "次のdependency-ready Workを1件選択してください。"
            "repository code・design file・branch・PRを変更せず、"
            "merge/reviewも実行しないでください。"
            "#450へ日本語のMission Checkpointを1回だけ記録し、"
            "選択したWorkは必ずliteral field `- current Work: #<issue>` で記録してください。"
            "active PRが存在する場合は `- current PR: #<pr>` と"
            " `- exact HEAD: <40-hex-sha>` も記録してください。"
            "active PRが無い場合はPR/HEADを捏造せず省略してください。"
            "`選択した次Work:`等の別名だけでcurrent Workを代用してはいけません。"
            "外部待機状態を選ぶ場合も、再開対象Workがあるなら"
            "同じliteral current Work fieldを必ず残してください。"
            "Root #317 completionをlive evidenceで証明できない限り"
            "MISSION_COMPLETEにしないでください。"
        )
        return self._run_codex(instruction)

    def _run_codex(self, instruction: str) -> bool:
        result = self._runner.run(
            (*self._argv_prefix, instruction),
            cwd=self._root,
            environment=self._environment,
            timeout_seconds=1800,
            capture_output=False,
        )
        return result.succeeded


class HostLoopController:
    def __init__(self, mission: MissionPort, implementer: ImplementerPort) -> None:
        self._mission = mission
        self._implementer = implementer

    def run_once(self) -> HostTransitionResult:
        try:
            target = self._mission.current_target()
        except RuntimeError as error:
            return HostTransitionResult(
                HostTransitionStatus.INTERVENTION_REQUIRED,
                _observe_failure_detail(error),
            )
        if target is None:
            if self._implementer.plan_next_work(None):
                return HostTransitionResult(HostTransitionStatus.COMPLETED, "PLANNING_DISPATCHED")
            return HostTransitionResult(
                HostTransitionStatus.INTERVENTION_REQUIRED, "PLANNING_UNAVAILABLE"
            )
        if target.stale_checkpoint:
            return _target_result(
                HostTransitionStatus.INTERVENTION_REQUIRED, "STALE_MISSION_CHECKPOINT", target
            )
        if target.merged or not target.issue_open:
            if target.issue_open and not self._mission.complete_work(target):
                return _target_result(
                    HostTransitionStatus.INTERVENTION_REQUIRED, "WORK_CLOSE_FAILED", target
                )
            if not self._implementer.plan_next_work(target.work_issue):
                return _target_result(
                    HostTransitionStatus.INTERVENTION_REQUIRED, "NEXT_WORK_PLANNING_FAILED", target
                )
            return _target_result(HostTransitionStatus.COMPLETED, "WORK_RECONCILED", target)
        if target.pr_number is None or target.head_sha is None:
            if self._implementer.continue_work(target, repair=False):
                return _target_result(HostTransitionStatus.COMPLETED, "IMPLEMENTER_DISPATCHED", target)
            return _target_result(
                HostTransitionStatus.INTERVENTION_REQUIRED, "IMPLEMENTER_UNAVAILABLE", target
            )
        try:
            ci = self._mission.ci_status(target)
        except RuntimeError:
            return _target_result(
                HostTransitionStatus.INTERVENTION_REQUIRED, "CI_OBSERVE_FAILED", target
            )
        if ci is CIGateStatus.STALE:
            return _target_result(HostTransitionStatus.INTERVENTION_REQUIRED, "STALE_CI", target)
        if ci is CIGateStatus.YIELD_EXTERNAL:
            return _target_result(HostTransitionStatus.YIELD_EXTERNAL, "CI_PENDING", target)
        if ci is CIGateStatus.FAILED:
            if self._implementer.continue_work(target, repair=True):
                return _target_result(HostTransitionStatus.COMPLETED, "CI_REPAIR_DISPATCHED", target)
            return _target_result(
                HostTransitionStatus.INTERVENTION_REQUIRED, "CI_REPAIR_UNAVAILABLE", target
            )
        try:
            merged = self._mission.merge_current(target)
        except RuntimeError:
            merged = False
        if not merged:
            return _target_result(
                HostTransitionStatus.INTERVENTION_REQUIRED, "EXPECTED_HEAD_MERGE_FAILED", target
            )
        if not self._mission.complete_work(target):
            return _target_result(
                HostTransitionStatus.INTERVENTION_REQUIRED, "WORK_CLOSE_FAILED", target
            )
        checkpoint = (
            "## Mission Checkpoint — functional completion / next selection\n\n"
            "- Mission state: `ACTIVE`\n"
            f"- completed Work: #{target.work_issue}\n"
            f"- merged PR: #{target.pr_number}\n"
            f"- merged exact HEAD: `{target.head_sha}`\n"
            "- review policy: non-functional findings / `NOT_RUN` are non-blocking\n"
            "- next action: Project #7とGitHub liveから次のdependency-ready Workをfresh選択する"
        )
        if not self._mission.publish_checkpoint(checkpoint):
            return _target_result(
                HostTransitionStatus.INTERVENTION_REQUIRED, "CHECKPOINT_PUBLISH_FAILED", target
            )
        if not self._implementer.plan_next_work(target.work_issue):
            return _target_result(
                HostTransitionStatus.INTERVENTION_REQUIRED, "NEXT_WORK_PLANNING_FAILED", target
            )
        return _target_result(HostTransitionStatus.COMPLETED, "WORK_MERGED", target)


def run_host_transition(
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
        return HostTransitionResult(
            HostTransitionStatus.INTERVENTION_REQUIRED,
            "PREFLIGHT_BLOCKED:" + ",".join(preflight.blocking_for_loop_bootstrap),
        )
    runner = local_runner or SubprocessLocalRunner()
    try:
        argv_prefix = _codex_argv(values)
    except ValueError:
        return HostTransitionResult(
            HostTransitionStatus.INTERVENTION_REQUIRED, "CODEX_COMMAND_INVALID"
        )
    controller = HostLoopController(
        GhMissionPort(runner, values),
        CodexImplementer(runner, project_root, values, argv_prefix),
    )
    return controller.run_once()


def _with_goal_identity(root: Path, environment: Mapping[str, str]) -> dict[str, str]:
    values = dict(environment)
    goal = root / "docs" / "operations" / "loop_mission_goal.md"
    if not goal.is_file():
        return values
    content = goal.read_bytes()
    lines = content.decode("utf-8").splitlines()
    version = next((line.removeprefix("version: ") for line in lines if line.startswith("version: ")), "")
    generation = next(
        (line.removeprefix("generation: ") for line in lines if line.startswith("generation: ")),
        "",
    )
    values.setdefault("CODEX_MISSION_GOAL_VERSION", version)
    values.setdefault("CODEX_MISSION_GOAL_GENERATION", generation)
    values.setdefault("CODEX_MISSION_GOAL_SHA256", hashlib.sha256(content).hexdigest())
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


def _github_environment(environment: Mapping[str, str]) -> dict[str, str]:
    allowed = {"PATH", "HOME", "GH_TOKEN", "LANG", "LC_ALL", "TMPDIR"}
    return {key: value for key, value in environment.items() if key in allowed}


def _codex_environment(environment: Mapping[str, str]) -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "GH_TOKEN",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "CODEX_HOME",
        "XDG_CONFIG_HOME",
        "CODEX_MISSION_GOAL_VERSION",
        "CODEX_MISSION_GOAL_GENERATION",
        "CODEX_MISSION_GOAL_SHA256",
    }
    return {key: value for key, value in environment.items() if key in allowed}


def _observe_failure_detail(error: RuntimeError) -> str:
    reason = str(error)
    if reason in _SAFE_OBSERVE_FAILURES:
        return f"GITHUB_OBSERVE_FAILED:{reason}"
    return "GITHUB_OBSERVE_FAILED"


def _target_result(
    status: HostTransitionStatus, detail: str, target: HostTarget
) -> HostTransitionResult:
    return HostTransitionResult(status, detail, target.work_issue, target.pr_number, target.head_sha)


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value: object) -> int:
    return value if isinstance(value, int) else 0


def _nested_string(value: Mapping[str, object], key: str, nested: str) -> str | None:
    child = value.get(key)
    if not isinstance(child, dict):
        return None
    return _string(cast(dict[str, object], child).get(nested))
