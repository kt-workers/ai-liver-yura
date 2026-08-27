from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

import pytest

from tools.loop_engine.github_issues import (
    GitHubImprovementIssuePublisher,
    improvement_intent,
)
from tools.loop_engine.health import marker, plan_improvements, render_issue_body
from tools.loop_engine.models import (
    ExistingImprovementIssue,
    ImprovementCandidate,
    ImprovementIssueIntent,
    ImprovementSeverity,
    LoopHealthEvent,
    LoopHealthKind,
    MissionSnapshot,
)
from tools.loop_engine.supervisor import MissionSupervisor

from .conftest import epoch, identity


def test_second_same_intervention_generates_p0_improvement() -> None:
    prior = LoopHealthEvent(
        LoopHealthKind.MANUAL_INTERVENTION,
        "MISSION_CHECKPOINT_STALE",
        1,
        (465,),
        ("conflict:MISSION_CHECKPOINT_STALE",),
        1,
        True,
    )
    observed = replace(
        epoch(mission=MissionSnapshot(identity("issue", "450"), 465, True)),
        health_events=(prior,),
    )
    decision = MissionSupervisor().decide(observed, planning_date=date(2026, 8, 27))
    candidate = decision.improvement_candidates[0]
    assert candidate.kind is LoopHealthKind.MANUAL_INTERVENTION
    assert candidate.severity is ImprovementSeverity.P0
    assert candidate.start_date == "2026-08-27"
    assert candidate.target_date == "2026-08-29"


def test_repeated_failure_generates_candidate_without_stopping_current_work() -> None:
    event = LoopHealthEvent(
        LoopHealthKind.REPEATED_FAILURE,
        "review-provider-timeout",
        3,
        source_refs=("run:10", "run:11", "run:12"),
    )
    observed = replace(epoch(), health_events=(event,))
    decision = MissionSupervisor().decide(observed, planning_date=date(2026, 8, 27))
    assert decision.task_packet is not None
    assert decision.improvement_candidates[0].kind is LoopHealthKind.REPEATED_FAILURE


def test_open_improvement_issue_suppresses_duplicate() -> None:
    event = LoopHealthEvent(LoopHealthKind.NO_PROGRESS, "same-state", 2)
    first = plan_improvements(
        (event,),
        existing_issues=(),
        checkpoint_keys=(),
        planning_date=date(2026, 8, 27),
    )[0]
    candidates = plan_improvements(
        (event,),
        existing_issues=(ExistingImprovementIssue(500, first.improvement_key, "open"),),
        checkpoint_keys=(),
        planning_date=date(2026, 8, 27),
    )
    assert candidates == ()


def test_candidate_generation_is_bounded_to_three() -> None:
    events = tuple(
        LoopHealthEvent(LoopHealthKind.REPEATED_FAILURE, f"failure-{index}", 3)
        for index in range(10)
    )
    candidates = plan_improvements(
        events,
        existing_issues=(),
        checkpoint_keys=(),
        planning_date=date(2026, 8, 27),
    )
    assert len(candidates) == 3


def test_generated_issue_body_has_durable_marker_and_dates() -> None:
    candidate = _candidate()
    body = render_issue_body(candidate)
    assert marker(candidate.improvement_key) in body
    assert "Start date: `2026-08-27`" in body
    assert "Target date: `2026-08-31`" in body
    assert "Project #6" in body


class FakeRunner:
    def __init__(self, *, existing: bool = False) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.existing = existing

    def run(self, args: Sequence[str]) -> str:
        command = tuple(args)
        self.commands.append(command)
        if command[:3] == ("gh", "issue", "list"):
            if not self.existing:
                return "[]"
            candidate = _candidate()
            return json.dumps(
                [
                    {
                        "number": 501,
                        "url": "https://github.com/ktan514/ai-liver-yura/issues/501",
                        "body": marker(candidate.improvement_key),
                    }
                ]
            )
        if command[:3] == ("gh", "issue", "create"):
            return "https://github.com/ktan514/ai-liver-yura/issues/502\n"
        if command[:4] == ("gh", "project", "view", "7"):
            return '{"id":"PVT7"}'
        if command[:4] == ("gh", "project", "item-list", "7"):
            return '{"items":[]}'
        if command[:4] == ("gh", "project", "item-add", "7"):
            return '{"id":"ITEM7"}'
        if command[:4] == ("gh", "project", "field-list", "7"):
            return json.dumps(
                {
                    "fields": [
                        {
                            "name": "Status",
                            "id": "F_STATUS",
                            "options": [{"name": "Ready", "id": "O_READY"}],
                        },
                        {
                            "name": "Priority",
                            "id": "F_PRIORITY",
                            "options": [{"name": "P1", "id": "O_P1"}],
                        },
                        {
                            "name": "Area",
                            "id": "F_AREA",
                            "options": [
                                {
                                    "name": "Subsystem/Development Tooling",
                                    "id": "O_AREA",
                                }
                            ],
                        },
                        {
                            "name": "Issue level",
                            "id": "F_LEVEL",
                            "options": [{"name": "Work", "id": "O_WORK"}],
                        },
                        {"name": "Start date", "id": "F_START"},
                        {"name": "Target date", "id": "F_TARGET"},
                    ]
                }
            )
        if command[:3] == ("gh", "project", "item-edit"):
            return ""
        raise AssertionError(command)


def test_publisher_creates_loop_issue_and_project_7_fields() -> None:
    runner = FakeRunner()
    result = GitHubImprovementIssuePublisher(runner).publish(improvement_intent(_candidate()))
    assert result.created
    assert result.issue_number == 502
    flat = "\n".join(" ".join(command) for command in runner.commands)
    assert "gh issue create" in flat
    assert "--label loop-engineering" in flat
    assert "gh project view 7" in flat
    assert "gh project item-add 7" in flat
    assert " 6 --owner" not in flat


def test_publisher_dedupes_existing_open_issue() -> None:
    runner = FakeRunner(existing=True)
    result = GitHubImprovementIssuePublisher(runner).publish(improvement_intent(_candidate()))
    assert not result.created
    assert result.issue_number == 501
    assert not any(command[:3] == ("gh", "issue", "create") for command in runner.commands)


def test_publisher_hard_rejects_project_6() -> None:
    candidate = _candidate()
    bad = ImprovementIssueIntent(
        "ktan514/ai-liver-yura",
        6,
        "loop-engineering",
        "Ready",
        "Subsystem/Development Tooling",
        "Work",
        candidate,
    )
    with pytest.raises(ValueError, match="Project #6"):
        GitHubImprovementIssuePublisher(FakeRunner()).publish(bad)


def _candidate() -> ImprovementCandidate:
    event = LoopHealthEvent(LoopHealthKind.REPEATED_FAILURE, "provider-timeout", 3)
    return plan_improvements(
        (event,),
        existing_issues=(),
        checkpoint_keys=(),
        planning_date=date(2026, 8, 27),
    )[0]
