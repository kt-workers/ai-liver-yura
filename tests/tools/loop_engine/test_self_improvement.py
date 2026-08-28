from __future__ import annotations

import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

import pytest

from tools.loop_engine.github_issues import (
    GitHubImprovementIssuePublisher,
    improvement_intent,
)
from tools.loop_engine.health import marker, plan_improvements, render_issue_body
from tools.loop_engine.maintenance import (
    LoopMaintenanceCycle,
    SelfImprovementController,
)
from tools.loop_engine.models import (
    ExistingImprovementIssue,
    ImprovementCandidate,
    ImprovementIssueIntent,
    ImprovementPublishResult,
    ImprovementSeverity,
    LoopHealthEvent,
    LoopHealthKind,
    MissionSnapshot,
    RunDisposition,
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
    assert decision.disposition is RunDisposition.CONTINUE
    assert decision.task_packet is not None
    assert decision.improvement_candidates[0].kind is LoopHealthKind.REPEATED_FAILURE


def test_open_configured_improvement_issue_suppresses_duplicate() -> None:
    event = LoopHealthEvent(LoopHealthKind.NO_PROGRESS, "same-state", 2)
    first = _planned(event)
    candidates = plan_improvements(
        (event,),
        existing_issues=(ExistingImprovementIssue(500, first.improvement_key, "open"),),
        checkpoint_keys=(),
        planning_date=date(2026, 8, 27),
    )
    assert candidates == ()


def test_open_but_unconfigured_issue_is_replanned_for_project_repair() -> None:
    event = LoopHealthEvent(LoopHealthKind.NO_PROGRESS, "same-state", 2)
    first = _planned(event)
    candidates = plan_improvements(
        (event,),
        existing_issues=(
            ExistingImprovementIssue(500, first.improvement_key, "open", False),
        ),
        checkpoint_keys=(),
        planning_date=date(2026, 8, 27),
    )
    assert len(candidates) == 1
    assert candidates[0].improvement_key == first.improvement_key


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


def test_generated_issue_body_has_durable_marker_dates_and_parent() -> None:
    candidate = _candidate()
    body = render_issue_body(candidate)
    assert marker(candidate.improvement_key) in body
    assert "Parent: #462" in body
    assert "Start date: `2026-08-27`" in body
    assert "Target date: `2026-08-31`" in body
    assert "Project #6" in body


class FakeRunner:
    def __init__(self, *, existing: bool = False) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.existing = existing
        self.item_added = existing
        self.edit_count = 0

    def run(self, args: Sequence[str]) -> str:
        command = tuple(args)
        self.commands.append(command)
        if command[:2] == ("gh", "api"):
            if not self.existing:
                return "[[]]"
            candidate = _candidate()
            return json.dumps(
                [[
                    {
                        "number": 501,
                        "url": "https://api.github.com/repos/ktan514/ai-liver-yura/issues/501",
                        "body": marker(candidate.improvement_key),
                    }
                ]]
            )
        if command[:3] == ("gh", "issue", "create"):
            return "https://github.com/ktan514/ai-liver-yura/issues/502\n"
        if command[:4] == ("gh", "project", "view", "7"):
            return '{"id":"PVT7"}'
        if command[:4] == ("gh", "project", "item-list", "7"):
            if not self.item_added:
                return '{"items":[]}'
            number = 501 if self.existing else 502
            all_values: list[dict[str, object]] = [
                {"field": {"name": "Status"}, "name": "Ready"},
                {"field": {"name": "Priority"}, "name": "P1"},
                {"field": {"name": "Area"}, "name": "Subsystem/Development Tooling"},
                {"field": {"name": "Issue level"}, "name": "Work"},
                {"field": {"name": "Start date"}, "date": "2026-08-27"},
                {"field": {"name": "Target date"}, "date": "2026-08-31"},
            ]
            values = all_values[: self.edit_count]
            return json.dumps(
                {
                    "items": [
                        {
                            "id": "ITEM7",
                            "content": {
                                "url": "https://github.com/ktan514/ai-liver-yura/issues/"
                                f"{number}",
                            },
                            "fieldValues": values,
                        }
                    ]
                }
            )
        if command[:4] == ("gh", "project", "item-add", "7"):
            self.item_added = True
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
            self.edit_count += 1
            return ""
        raise AssertionError(command)


def test_publisher_creates_loop_issue_and_project_7_fields() -> None:
    runner = FakeRunner()
    result = GitHubImprovementIssuePublisher(runner).publish(improvement_intent(_candidate()))
    assert result.created
    assert result.issue_number == 502
    flat = "\n".join(" ".join(command) for command in runner.commands)
    assert "gh issue create" in flat
    assert "gh api --paginate --slurp" in flat
    assert "--label loop-engineering" in flat
    assert "gh project view 7" in flat
    assert "gh project item-add 7" in flat
    assert "gh project item-list 7 --owner ktan514 --limit 100000" in flat
    assert " 6 --owner" not in flat


def test_publisher_reuses_existing_open_issue_and_repairs_project() -> None:
    runner = FakeRunner(existing=True)
    result = GitHubImprovementIssuePublisher(runner).publish(improvement_intent(_candidate()))
    assert not result.created
    assert result.issue_number == 501
    assert not any(command[:3] == ("gh", "issue", "create") for command in runner.commands)
    assert not any(command[:4] == ("gh", "project", "item-add", "7") for command in runner.commands)
    assert result.issue_url == "https://github.com/ktan514/ai-liver-yura/issues/501"


class LockAwareRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__()
        self.created_issue = False

    def run(self, args: Sequence[str]) -> str:
        command = tuple(args)
        if command[:2] == ("gh", "api"):
            if not self.created_issue:
                return "[[]]"
            candidate = _candidate()
            return json.dumps(
                [[{"number": 502, "body": marker(candidate.improvement_key)}]]
            )
        if command[:3] == ("gh", "issue", "create"):
            if self.created_issue:
                raise AssertionError("duplicate create")
            self.created_issue = True
            self.commands.append(command)
            return "https://github.com/ktan514/ai-liver-yura/issues/502\n"
        return super().run(args)


def test_publisher_keyed_lock_prevents_concurrent_duplicate_issue_create() -> None:
    runner = LockAwareRunner()
    publisher = GitHubImprovementIssuePublisher(runner)
    intent = improvement_intent(_candidate())
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(publisher.publish, (intent, intent)))
    assert sorted(result.created for result in results) == [False, True]
    assert sum(command[:3] == ("gh", "issue", "create") for command in runner.commands) == 1


class PagedMarkerRunner(FakeRunner):
    def run(self, args: Sequence[str]) -> str:
        command = tuple(args)
        if command[:2] == ("gh", "api"):
            candidate = _candidate()
            return json.dumps(
                [
                    [],
                    [
                        {
                            "number": 601,
                            "url": "https://github.com/ktan514/ai-liver-yura/issues/601",
                            "body": marker(candidate.improvement_key),
                        }
                    ],
                ]
            )
        return super().run(args)


def test_publisher_searches_all_paginated_issue_pages_for_marker() -> None:
    found = GitHubImprovementIssuePublisher(PagedMarkerRunner())._find_open_issue(
        _candidate().improvement_key
    )
    assert found == (601, "https://github.com/ktan514/ai-liver-yura/issues/601")


class MismatchedReadbackRunner(FakeRunner):
    def run(self, args: Sequence[str]) -> str:
        command = tuple(args)
        value = super().run(args)
        if command[:4] == ("gh", "project", "item-list", "7") and self.edit_count >= 6:
            payload = json.loads(value)
            payload["items"][0]["fieldValues"][0]["name"] = "Blocked"
            return json.dumps(payload)
        return value


def test_publisher_fails_closed_when_project_effect_readback_mismatches() -> None:
    with pytest.raises(ValueError, match="MUTATION_EFFECT_MISMATCH"):
        GitHubImprovementIssuePublisher(MismatchedReadbackRunner()).publish(
            improvement_intent(_candidate())
        )


class StaleFieldIdentityRunner(FakeRunner):
    def run(self, args: Sequence[str]) -> str:
        command = tuple(args)
        value = super().run(args)
        if command[:4] == ("gh", "project", "field-list", "7") and self.edit_count >= 1:
            payload = json.loads(value)
            payload["fields"][0]["id"] = "F_STATUS_REPLACED"
            return json.dumps(payload)
        return value


def test_publisher_rechecks_write_gate_before_each_project_field_mutation() -> None:
    runner = StaleFieldIdentityRunner()
    with pytest.raises(ValueError, match="STALE_WRITE_GATE"):
        GitHubImprovementIssuePublisher(runner).publish(improvement_intent(_candidate()))
    assert runner.edit_count == 1


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


def test_issue_body_redacts_credential_like_health_fingerprint_and_source_reference() -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
    candidate = _planned(
        LoopHealthEvent(
            LoopHealthKind.REPEATED_FAILURE,
            secret,
            3,
            source_refs=("ghp_abcdefghijklmnopqrstuvwxyz0123456789",),
        )
    )
    body = render_issue_body(candidate)
    assert secret not in body
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in body
    assert "sha256:" in body


class RecordingPublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.intents: list[ImprovementIssueIntent] = []

    def publish(self, intent: ImprovementIssueIntent) -> ImprovementPublishResult:
        self.intents.append(intent)
        if self.fail:
            raise RuntimeError("raw secret-bearing failure must not escape")
        return ImprovementPublishResult(
            600,
            "https://github.com/ktan514/ai-liver-yura/issues/600",
            True,
            True,
        )


def test_maintenance_cycle_publishes_candidate_in_same_iteration() -> None:
    event = LoopHealthEvent(LoopHealthKind.REPEATED_FAILURE, "provider-timeout", 3)
    observed = replace(epoch(), health_events=(event,))
    publisher = RecordingPublisher()
    cycle = LoopMaintenanceCycle(
        MissionSupervisor(),
        SelfImprovementController(publisher),
    )
    result = cycle.run(observed, planning_date=date(2026, 8, 27))
    assert result.decision.disposition is RunDisposition.CONTINUE
    assert len(result.publication.published) == 1
    assert result.publication.failures == ()
    assert publisher.intents[0].label == "loop-engineering"
    assert publisher.intents[0].project_number == 7


def test_publisher_failure_is_typed_and_does_not_replace_primary_decision() -> None:
    event = LoopHealthEvent(LoopHealthKind.REPEATED_FAILURE, "provider-timeout", 3)
    observed = replace(epoch(), health_events=(event,))
    cycle = LoopMaintenanceCycle(
        MissionSupervisor(),
        SelfImprovementController(RecordingPublisher(fail=True)),
    )
    result = cycle.run(observed, planning_date=date(2026, 8, 27))
    assert result.decision.disposition is RunDisposition.CONTINUE
    assert result.publication.published == ()
    assert len(result.publication.failures) == 1
    assert result.publication.failures[0].reason == "IMPROVEMENT_PUBLISH_FAILED"
    assert "secret-bearing" not in repr(result.publication.failures)


def _planned(event: LoopHealthEvent) -> ImprovementCandidate:
    return plan_improvements(
        (event,),
        existing_issues=(),
        checkpoint_keys=(),
        planning_date=date(2026, 8, 27),
    )[0]


def _candidate() -> ImprovementCandidate:
    event = LoopHealthEvent(LoopHealthKind.REPEATED_FAILURE, "provider-timeout", 3)
    return _planned(event)
