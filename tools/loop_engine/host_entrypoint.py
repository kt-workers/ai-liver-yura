"""Loop Engineを実ホストへ安全に接続する入口。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
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
from .trusted_worktree import TrustedWorktree

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
    """最新のMission Checkpointだけを採用し、古い対象へ戻らない。"""

    def __init__(self, runner: LocalRunner, environment: Mapping[str, str]) -> None:
        super().__init__(runner, environment)
        self._merge_conflict_target: tuple[int, int, str] | None = None

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

    def merge_current(self, target: HostTarget) -> bool:
        self._merge_conflict_target = None
        if self._pull_requires_reconciliation(target):
            self._remember_merge_conflict(target)
            return False

        merged = super().merge_current(target)
        if merged:
            return True

        if self._pull_requires_reconciliation(target):
            self._remember_merge_conflict(target)
        return False

    def merge_requires_reconciliation(self, target: HostTarget) -> bool:
        if target.pr_number is None or target.head_sha is None:
            return False
        return self._merge_conflict_target == (
            target.work_issue,
            target.pr_number,
            target.head_sha,
        )

    def _pull_requires_reconciliation(self, target: HostTarget) -> bool:
        if target.pr_number is None or target.head_sha is None:
            return False
        pull = self._api_json(f"repos/ktan514/ai-liver-yura/pulls/{target.pr_number}")
        head_value = pull.get("head")
        if not isinstance(head_value, dict) or head_value.get("sha") != target.head_sha:
            return False
        mergeable_state = pull.get("mergeable_state")
        return pull.get("mergeable") is False or mergeable_state == "dirty"

    def _remember_merge_conflict(self, target: HostTarget) -> None:
        assert target.pr_number is not None
        assert target.head_sha is not None
        self._merge_conflict_target = (
            target.work_issue,
            target.pr_number,
            target.head_sha,
        )


class PilotAwareMissionPort(MissionPort):
    """#471の基盤統合後も、実製品作業の試験完了までは統合Issueを開いたままにする。"""

    def __init__(self, delegate: MissionPort) -> None:
        self._delegate = delegate
        self._bootstrap_target: HostTarget | None = None

    def current_target(self) -> HostTarget | None:
        return self._delegate.current_target()

    def ci_status(self, target: HostTarget) -> CIGateStatus:
        return self._delegate.ci_status(target)

    def merge_current(self, target: HostTarget) -> bool:
        return self._delegate.merge_current(target)

    def merge_requires_reconciliation(self, target: HostTarget) -> bool:
        if not isinstance(self._delegate, StrictGhMissionPort):
            return False
        return self._delegate.merge_requires_reconciliation(target)

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
            "## Mission Checkpoint — ACTIVE / 実製品試験が必要\n\n"
            "- Mission state: `ACTIVE`\n"
            f"- current Work: #{target.work_issue}\n"
            f"{pr_line}"
            f"{head_line}"
            "- #477 基盤統合: mergeとGitHub再確認は完了\n"
            "- #471 状態: openのまま実製品Workの試験証拠を待つ\n"
            "- next action: Project #7とGitHub liveから実製品の試験対象Workを1件fresh選択する\n"
            "- review policy: 非機能の指摘と`NOT_RUN`は停止条件にしない"
        )
        return self._delegate.publish_checkpoint(checkpoint)


class PilotPlanningImplementer(CodexImplementer):
    """実製品試験の選択と、Codex編集後の信頼済みGit操作を担当する。"""

    def __init__(
        self,
        runner: LocalRunner,
        root: Path,
        environment: Mapping[str, str],
        argv_prefix: Sequence[str],
    ) -> None:
        super().__init__(runner, root, environment, argv_prefix)
        self._trusted_worktree = TrustedWorktree(runner, root, environment)

    def continue_work(self, target: HostTarget, *, repair: bool) -> bool:
        prepared = self._trusted_worktree.prepare(target)
        if prepared is None:
            return False

        if prepared.reconciliation_started:
            task = (
                "現在の作業系統へ最新基幹を通常mergeした状態を確認し、"
                "競合箇所をRepository正本に従って解消してください。"
            )
        elif repair:
            task = (
                "現在のexact HEADで実際に動作を妨げている不具合だけを修正してください。"
            )
        else:
            task = "現在Workの次の実装工程を1回分だけ進めてください。"

        pr_text = (
            f"PR #{target.pr_number}"
            if target.pr_number is not None
            else "まだPRがない現在Work"
        )
        instruction = (
            f"Mission #450 / Parent #462 の current Work #{target.work_issue}（{pr_text}）を"
            "1回分の限定された遷移として進めます。"
            f"{task}"
            "GitHubの現在状態、最新Mission Checkpoint、現在基幹、Repository正本、"
            "Work固有の再開確認（Resume Gate）と依存状態をfresh readしてください。"
            "設計→コード→テストの順序を守ってください。"
            "コードや文書内の人間向け文章は日本語で記述し、英語の概念名が必要な場合は"
            "自然な日本語の意味表現を先に書いてから原語を括弧内へ併記してください。"
            "Gitのbranch作成・切替・merge・add・commit・push・rebase・force pushは"
            "実行しないでください。Git metadataの変更は信頼済みホストが担当します。"
            "GitHubへのIssue/PR/Checkpoint等の書込みも行わないでください。"
            "ファイル編集と必要なmachine gateだけを実施し、変更はworktreeへ未commitで残してください。"
            "正本レビュー（canonical review）の非機能指摘やprovider `NOT_RUN`を理由に停止せず、"
            "Project #6の変更とreviewer credential利用は禁止です。"
        )
        if not self._run_codex(instruction):
            self._trusted_worktree.abort_merge_if_needed(prepared)
            return False
        finalized = self._trusted_worktree.finalize(target, prepared, repair=repair)
        return finalized is not None

    def plan_next_work(self, completed_work: int | None) -> bool:
        if completed_work != _INTEGRATION_WORK:
            return super().plan_next_work(completed_work)
        instruction = (
            "Mission #450の実製品試験対象を選択する計画専用の遷移です。"
            "Loop Engineeringの基盤統合 #471/#477は基幹へ統合済みです。"
            "#471は実製品試験の証拠待ちでopenのままです。"
            "#207/#317/#450/#462、Project #7、GitHub上の現在Issue/PRをfresh readし、"
            "依存関係を満たしたV2製品Workまたは統合Workを1件選択してください。"
            "#462/#471自身とLoop Engineering基盤責務のIssueは試験候補から除外してください。"
            "依存関係を満たした製品Workが無い場合は、外部または依存待ちをCheckpointへ明示してください。"
            "Repositoryのコード・設計file・branch・PRを変更せず、mergeやreviewも実行しないでください。"
            "選択したWorkは必ずliteral field `- current Work: #<issue>` で記録してください。"
            "active PRが存在する場合は `- current PR: #<pr>` と"
            " `- exact HEAD: <40-hex-sha>` も記録してください。"
            "active PRが無い場合はPR/HEADを捏造せず省略してください。"
            "#450へ日本語のMission Checkpointを1回だけ記録してください。"
            "Root #317の完成をlive evidenceで証明できない限りMISSION_COMPLETEにしないでください。"
        )
        return self._run_codex(instruction)


class ReconciliationAwareHostLoopController(HostLoopController):
    """merge競合と#471の実製品試験計画を限定された遷移へ振り分ける。"""

    def __init__(
        self,
        mission: PilotAwareMissionPort,
        implementer: PilotPlanningImplementer,
    ) -> None:
        super().__init__(mission, implementer)
        self._reconciliation_mission = mission
        self._reconciliation_implementer = implementer

    def run_once(self) -> HostTransitionResult:
        try:
            initial_target = self._reconciliation_mission.current_target()
        except RuntimeError:
            initial_target = None

        if (
            initial_target is not None
            and initial_target.work_issue == _INTEGRATION_WORK
            and initial_target.issue_open
            and initial_target.pr_number is None
        ):
            return self._run_pilot_planning(initial_target)

        result = super().run_once()
        if (
            result.status is HostTransitionStatus.INTERVENTION_REQUIRED
            and result.detail == "EXPECTED_HEAD_MERGE_FAILED"
        ):
            result = self._run_merge_reconciliation(result)

        if (
            initial_target is not None
            and result.status is HostTransitionStatus.COMPLETED
            and result.detail
            in {
                "IMPLEMENTER_DISPATCHED",
                "CI_REPAIR_DISPATCHED",
                "MERGE_RECONCILIATION_DISPATCHED",
            }
        ):
            return self._verify_implementation_progress(initial_target, result)
        return result

    def _run_pilot_planning(self, target: HostTarget) -> HostTransitionResult:
        before_checkpoint = target.checkpoint_comment_id
        if not self._reconciliation_implementer.plan_next_work(_INTEGRATION_WORK):
            return HostTransitionResult(
                HostTransitionStatus.INTERVENTION_REQUIRED,
                "PILOT_PLANNING_UNAVAILABLE",
                target.work_issue,
            )
        try:
            fresh = self._reconciliation_mission.current_target()
        except RuntimeError:
            fresh = None
        if fresh is None or fresh.checkpoint_comment_id == before_checkpoint:
            return HostTransitionResult(
                HostTransitionStatus.INTERVENTION_REQUIRED,
                "PILOT_PLANNING_NO_PROGRESS",
                target.work_issue,
            )
        if fresh.work_issue == _INTEGRATION_WORK:
            return HostTransitionResult(
                HostTransitionStatus.YIELD_EXTERNAL,
                "PILOT_DEPENDENCY_WAIT",
                target.work_issue,
            )
        return HostTransitionResult(
            HostTransitionStatus.COMPLETED,
            "PILOT_PLANNING_DISPATCHED",
            fresh.work_issue,
            fresh.pr_number,
            fresh.head_sha,
        )

    def _run_merge_reconciliation(
        self, result: HostTransitionResult
    ) -> HostTransitionResult:
        try:
            target = self._reconciliation_mission.current_target()
        except RuntimeError:
            return result
        if (
            target is None
            or target.work_issue != result.work_issue
            or target.pr_number != result.pr_number
            or target.head_sha != result.head_sha
            or not self._reconciliation_mission.merge_requires_reconciliation(target)
        ):
            return result

        if not self._reconciliation_implementer.continue_work(target, repair=True):
            return HostTransitionResult(
                HostTransitionStatus.INTERVENTION_REQUIRED,
                "MERGE_RECONCILIATION_FAILED",
                target.work_issue,
                target.pr_number,
                target.head_sha,
            )
        return HostTransitionResult(
            HostTransitionStatus.COMPLETED,
            "MERGE_RECONCILIATION_DISPATCHED",
            target.work_issue,
            target.pr_number,
            target.head_sha,
        )

    def _verify_implementation_progress(
        self,
        before: HostTarget,
        result: HostTransitionResult,
    ) -> HostTransitionResult:
        try:
            after = self._reconciliation_mission.current_target()
        except RuntimeError:
            after = None
        if after is None:
            return HostTransitionResult(
                HostTransitionStatus.INTERVENTION_REQUIRED,
                "IMPLEMENTER_PROGRESS_UNRESOLVED",
                before.work_issue,
                before.pr_number,
                before.head_sha,
            )
        identity_changed = (
            after.pr_number != before.pr_number or after.head_sha != before.head_sha
        )
        checkpoint_changed = after.checkpoint_comment_id != before.checkpoint_comment_id
        if not identity_changed or not checkpoint_changed:
            return HostTransitionResult(
                HostTransitionStatus.INTERVENTION_REQUIRED,
                "IMPLEMENTER_NO_PROGRESS",
                before.work_issue,
                before.pr_number,
                before.head_sha,
            )
        return result


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
    implementer = PilotPlanningImplementer(runner, project_root, values, argv_prefix)
    return ReconciliationAwareHostLoopController(mission, implementer).run_once()


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
        return (
            "codex",
            "-a",
            "never",
            "exec",
            "--sandbox",
            "workspace-write",
            "-c",
            "sandbox_workspace_write.network_access=true",
        )
    try:
        payload = json.loads(configured)
    except json.JSONDecodeError as error:
        raise ValueError("Codexコマンドが不正です") from error
    if not isinstance(payload, list) or not payload or not all(
        isinstance(item, str) and item for item in payload
    ):
        raise ValueError("Codexコマンドが不正です")
    return tuple(cast(list[str], payload))
