"""Trusted-host GitHub publisher for Loop Engineering improvement Work."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .health import marker, render_issue_body
from .models import (
    ImprovementCandidate,
    ImprovementIssueIntent,
    ImprovementPublishResult,
)

_REPOSITORY = "ktan514/ai-liver-yura"
_OWNER = "ktan514"
_PROJECT_NUMBER = 7
_LABEL = "loop-engineering"


class CommandRunner(Protocol):
    def run(self, args: Sequence[str]) -> str:
        """Run a trusted, fixed-shape command and return stdout."""


@dataclass(slots=True)
class SubprocessCommandRunner:
    timeout_seconds: float = 30.0

    def run(self, args: Sequence[str]) -> str:
        completed = subprocess.run(
            tuple(args),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=self.timeout_seconds,
        )
        return completed.stdout


@dataclass(slots=True)
class GitHubImprovementIssuePublisher:
    runner: CommandRunner

    def publish(self, intent: ImprovementIssueIntent) -> ImprovementPublishResult:
        self._validate_intent(intent)
        existing = self._find_open_issue(intent.candidate.improvement_key)
        if existing is None:
            issue_url = self.runner.run(
                (
                    "gh",
                    "issue",
                    "create",
                    "--repo",
                    _REPOSITORY,
                    "--title",
                    intent.candidate.title,
                    "--body",
                    render_issue_body(intent.candidate),
                    "--label",
                    _LABEL,
                )
            ).strip()
            issue_number = _issue_number(issue_url)
            created = True
        else:
            issue_number, issue_url = existing
            created = False

        self._ensure_project_configuration(issue_url, intent)
        return ImprovementPublishResult(issue_number, issue_url, created, True)

    def _find_open_issue(self, improvement_key: str) -> tuple[int, str] | None:
        raw = self.runner.run(
            (
                "gh",
                "issue",
                "list",
                "--repo",
                _REPOSITORY,
                "--state",
                "open",
                "--label",
                _LABEL,
                "--limit",
                "100",
                "--json",
                "number,body,url",
            )
        )
        for item in _object_list(raw):
            body = _optional_string(item.get("body")) or ""
            if marker(improvement_key) not in body:
                continue
            number = _integer(item.get("number"), "issue.number")
            url = _string(item.get("url"), "issue.url")
            return number, url
        return None

    def _ensure_project_configuration(
        self,
        issue_url: str,
        intent: ImprovementIssueIntent,
    ) -> None:
        project = _object(
            self.runner.run(
                (
                    "gh",
                    "project",
                    "view",
                    str(_PROJECT_NUMBER),
                    "--owner",
                    _OWNER,
                    "--format",
                    "json",
                )
            )
        )
        project_id = _string(project.get("id"), "project.id")

        item_id = self._project_item_id(issue_url)
        if item_id is None:
            added = _object(
                self.runner.run(
                    (
                        "gh",
                        "project",
                        "item-add",
                        str(_PROJECT_NUMBER),
                        "--owner",
                        _OWNER,
                        "--url",
                        issue_url,
                        "--format",
                        "json",
                    )
                )
            )
            item_id = _string(added.get("id"), "project_item.id")

        fields = self._fields()
        self._edit_single_select(project_id, item_id, fields, "Status", intent.status)
        self._edit_single_select(
            project_id,
            item_id,
            fields,
            "Priority",
            intent.candidate.severity.value,
        )
        self._edit_single_select(project_id, item_id, fields, "Area", intent.area)
        self._edit_single_select(project_id, item_id, fields, "Issue level", intent.issue_level)
        self._edit_date(
            project_id,
            item_id,
            fields,
            "Start date",
            intent.candidate.start_date,
        )
        self._edit_date(
            project_id,
            item_id,
            fields,
            "Target date",
            intent.candidate.target_date,
        )

    def _project_item_id(self, issue_url: str) -> str | None:
        payload = _object(
            self.runner.run(
                (
                    "gh",
                    "project",
                    "item-list",
                    str(_PROJECT_NUMBER),
                    "--owner",
                    _OWNER,
                    "--limit",
                    "1000",
                    "--format",
                    "json",
                )
            )
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("project.items missing")
        for raw in items:
            if not isinstance(raw, dict):
                continue
            content = raw.get("content")
            if not isinstance(content, dict) or content.get("url") != issue_url:
                continue
            return _string(raw.get("id"), "project_item.id")
        return None

    def _fields(self) -> dict[str, dict[str, object]]:
        payload = _object(
            self.runner.run(
                (
                    "gh",
                    "project",
                    "field-list",
                    str(_PROJECT_NUMBER),
                    "--owner",
                    _OWNER,
                    "--format",
                    "json",
                )
            )
        )
        raw_fields = payload.get("fields")
        if not isinstance(raw_fields, list):
            raise ValueError("project.fields missing")
        result: dict[str, dict[str, object]] = {}
        for raw in raw_fields:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            if isinstance(name, str):
                result[name] = raw
        return result

    def _edit_single_select(
        self,
        project_id: str,
        item_id: str,
        fields: dict[str, dict[str, object]],
        field_name: str,
        option_name: str,
    ) -> None:
        field = _field(fields, field_name)
        field_id = _string(field.get("id"), f"{field_name}.id")
        options = field.get("options")
        if not isinstance(options, list):
            raise ValueError(f"{field_name}.options missing")
        option_id: str | None = None
        for raw in options:
            if isinstance(raw, dict) and raw.get("name") == option_name:
                option_id = _string(raw.get("id"), f"{field_name}.option.id")
                break
        if option_id is None:
            raise ValueError(f"{field_name} option unavailable: {option_name}")
        self.runner.run(
            (
                "gh",
                "project",
                "item-edit",
                "--id",
                item_id,
                "--project-id",
                project_id,
                "--field-id",
                field_id,
                "--single-select-option-id",
                option_id,
            )
        )

    def _edit_date(
        self,
        project_id: str,
        item_id: str,
        fields: dict[str, dict[str, object]],
        field_name: str,
        value: str,
    ) -> None:
        field = _field(fields, field_name)
        field_id = _string(field.get("id"), f"{field_name}.id")
        self.runner.run(
            (
                "gh",
                "project",
                "item-edit",
                "--id",
                item_id,
                "--project-id",
                project_id,
                "--field-id",
                field_id,
                "--date",
                value,
            )
        )

    @staticmethod
    def _validate_intent(intent: ImprovementIssueIntent) -> None:
        if intent.repository != _REPOSITORY:
            raise ValueError("unexpected repository")
        if intent.project_number != _PROJECT_NUMBER:
            raise ValueError("Project #6 and non-#7 targets are forbidden")
        if intent.label != _LABEL:
            raise ValueError("unexpected improvement label")


def improvement_intent(candidate: ImprovementCandidate) -> ImprovementIssueIntent:
    return ImprovementIssueIntent(
        repository=_REPOSITORY,
        project_number=_PROJECT_NUMBER,
        label=_LABEL,
        status="Ready",
        area="Subsystem/Development Tooling",
        issue_level="Work",
        candidate=candidate,
    )


def _issue_number(url: str) -> int:
    value = url.rstrip("/").rsplit("/", 1)[-1]
    if not value.isdigit():
        raise ValueError("GitHub issue create did not return an issue URL")
    return int(value)


def _object(raw: str) -> dict[str, object]:
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _object_list(raw: str) -> list[dict[str, object]]:
    value: object = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("expected JSON array")
    result: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(item)
    return result


def _field(
    fields: dict[str, dict[str, object]],
    name: str,
) -> dict[str, object]:
    try:
        return fields[name]
    except KeyError as exc:
        raise ValueError(f"Project #7 field unavailable: {name}") from exc


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} missing")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} missing")
    return value
