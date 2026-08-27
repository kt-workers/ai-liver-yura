"""Trusted-host GitHub publisher for Loop Engineering improvement Work."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .health import marker, render_issue_body
from .models import (
    ConflictKind,
    ImprovementCandidate,
    ImprovementIssueIntent,
    ImprovementPublishResult,
    WriteIntent,
)
from .write_gate import validate

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
                "api",
                "--paginate",
                "--slurp",
                f"repos/{_REPOSITORY}/issues?state=open&labels={_LABEL}&per_page=100",
            )
        )
        for item in _object_pages(raw):
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
            self._require_item_add_gate(project_id, issue_url)
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
            readback_item_id = self._project_item_id(issue_url)
            self._require_write_gate(
                WriteIntent(
                    "improvement-project-item-add-effect",
                    "project",
                    str(_PROJECT_NUMBER),
                    "add_improvement_item",
                    (),
                    (("item_id", item_id),),
                    "publisher-live-readback",
                ),
                {},
                {"item_id": readback_item_id or ""},
            )

        fields = self._fields()
        expected_preconditions = self._configuration_preconditions(
            project_id, item_id, fields, intent
        )
        fresh_preconditions = self._fresh_configuration_preconditions(issue_url, intent)
        self._require_write_gate(
            WriteIntent(
                "improvement-project-configure",
                "project",
                str(_PROJECT_NUMBER),
                "configure_improvement",
                tuple(expected_preconditions.items()),
                tuple(
                    (f"value:{name}", value)
                    for name, value in self._expected_values(intent).items()
                ),
                "publisher-live-readback",
            ),
            fresh_preconditions,
        )
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
        readback = self._project_field_values(issue_url)
        self._require_write_gate(
            WriteIntent(
                "improvement-project-effect",
                "project",
                str(_PROJECT_NUMBER),
                "configure_improvement",
                (),
                tuple(
                    (f"value:{name}", value)
                    for name, value in self._expected_values(intent).items()
                ),
                "publisher-live-readback",
            ),
            {},
            {f"value:{name}": value for name, value in readback.items()},
        )

    def _fresh_configuration_preconditions(
        self, issue_url: str, intent: ImprovementIssueIntent
    ) -> dict[str, str]:
        project = _object(
            self.runner.run(
                (
                    "gh", "project", "view", str(_PROJECT_NUMBER), "--owner", _OWNER,
                    "--format", "json",
                )
            )
        )
        item_id = self._project_item_id(issue_url)
        if item_id is None:
            raise ValueError("Project #7 item disappeared before mutation")
        return self._configuration_preconditions(
            _string(project.get("id"), "project.id"), item_id, self._fields(), intent
        )

    def _require_item_add_gate(self, project_id: str, issue_url: str) -> None:
        fresh_project = _object(
            self.runner.run(
                (
                    "gh", "project", "view", str(_PROJECT_NUMBER), "--owner", _OWNER,
                    "--format", "json",
                )
            )
        )
        fresh_item_id = self._project_item_id(issue_url)
        self._require_write_gate(
            WriteIntent(
                "improvement-project-item-add",
                "project",
                str(_PROJECT_NUMBER),
                "add_improvement_item",
                (("project_id", project_id), ("item_presence", "absent")),
                (),
                "publisher-live-readback",
            ),
            {
                "project_id": _string(fresh_project.get("id"), "project.id"),
                "item_presence": "present" if fresh_item_id is not None else "absent",
            },
        )

    def _configuration_preconditions(
        self,
        project_id: str,
        item_id: str,
        fields: dict[str, dict[str, object]],
        intent: ImprovementIssueIntent,
    ) -> dict[str, str]:
        values = self._expected_values(intent)
        result = {"project_id": project_id, "item_id": item_id}
        for field_name, option_name in values.items():
            field = _field(fields, field_name)
            result[f"field:{field_name}"] = _string(field.get("id"), f"{field_name}.id")
            if field_name in {"Start date", "Target date"}:
                continue
            options = field.get("options")
            if not isinstance(options, list):
                raise ValueError(f"{field_name}.options missing")
            option = next(
                (
                    item
                    for item in options
                    if isinstance(item, dict) and item.get("name") == option_name
                ),
                None,
            )
            if option is None:
                raise ValueError(f"{field_name} option unavailable: {option_name}")
            result[f"option:{field_name}"] = _string(option.get("id"), f"{field_name}.option.id")
        return result

    @staticmethod
    def _expected_values(intent: ImprovementIssueIntent) -> dict[str, str]:
        return {
            "Status": intent.status,
            "Priority": intent.candidate.severity.value,
            "Area": intent.area,
            "Issue level": intent.issue_level,
            "Start date": intent.candidate.start_date,
            "Target date": intent.candidate.target_date,
        }

    @staticmethod
    def _require_write_gate(
        intent: WriteIntent,
        fresh_preconditions: dict[str, str],
        readback_effect: dict[str, str] | None = None,
    ) -> None:
        result = validate(intent, fresh_preconditions, readback_effect)
        if not result.allowed:
            conflict = result.conflict or ConflictKind.STALE_WRITE_GATE
            raise ValueError(conflict.value)

    def _project_item_id(self, issue_url: str) -> str | None:
        snapshot = self._project_item(issue_url)
        return _optional_string(snapshot.get("id")) if snapshot is not None else None

    def _project_item(self, issue_url: str) -> dict[str, object] | None:
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
            _string(raw.get("id"), "project_item.id")
            return raw
        return None

    def _project_field_values(self, issue_url: str) -> dict[str, str]:
        item = self._project_item(issue_url)
        if item is None:
            return {}
        raw_values = item.get("fieldValues")
        if not isinstance(raw_values, list):
            return {}
        values: dict[str, str] = {}
        for raw in raw_values:
            if not isinstance(raw, dict):
                continue
            field = raw.get("field")
            name = field.get("name") if isinstance(field, dict) else None
            if not isinstance(name, str):
                continue
            value = raw.get("name")
            if not isinstance(value, str):
                value = raw.get("date")
            if isinstance(value, str):
                values[name] = value
        return values

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


def _object_pages(raw: str) -> list[dict[str, object]]:
    """Flatten every `gh api --paginate --slurp` page without a count cap."""
    value: object = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("expected paginated JSON array")
    result: list[dict[str, object]] = []
    for page in value:
        if not isinstance(page, list):
            raise ValueError("expected JSON page array")
        for item in page:
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
