from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import IssueGraphConfig
from .models import IssueNode, build_edges

JsonTransport = Callable[[Request], Any]

_REPOSITORY_ISSUES_QUERY = """
query($owner: String!, $repository: String!, $cursor: String) {
  repository(owner: $owner, name: $repository) {
    issues(first: 100, after: $cursor, states: [OPEN], orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number
        title
        body
        url
        state
        updatedAt
        parent { number }
        subIssues(first: 100) { nodes { number } }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

_PROJECT_QUERY = """
query($owner: String!, $projectNumber: Int!, $cursor: String) {
  user(login: $owner) {
    projectV2(number: $projectNumber) {
      title
      items(first: 100, after: $cursor) {
        nodes {
          id
          content {
            ... on Issue { number }
          }
          status: fieldValueByName(name: "Status") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
          issueLevel: fieldValueByName(name: "Issueレベル") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
          workType: fieldValueByName(name: "作業種別") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
          area: fieldValueByName(name: "領域") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
          priority: fieldValueByName(name: "優先度") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
          processNumber: fieldValueByName(name: "工程") {
            ... on ProjectV2ItemFieldNumberValue { number }
          }
          processText: fieldValueByName(name: "工程") {
            ... on ProjectV2ItemFieldTextValue { text }
          }
          startDate: fieldValueByName(name: "Start date") {
            ... on ProjectV2ItemFieldDateValue { date }
          }
          targetDate: fieldValueByName(name: "Target date") {
            ... on ProjectV2ItemFieldDateValue { date }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


@dataclass(slots=True)
class IssueGraphService:
    config: IssueGraphConfig
    transport: JsonTransport | None = None

    def load_graph(self) -> dict[str, Any]:
        diagnostics: list[str] = []
        degraded = False

        if self.config.token:
            try:
                nodes = self._load_graphql_issues()
            except GitHubApiError as error:
                degraded = True
                diagnostics.append(f"GraphQL Issue取得失敗: {error.public_message}")
                nodes = self._load_rest_issues(diagnostics)
        else:
            degraded = True
            diagnostics.append(
                "GITHUB_TOKEN未設定のためProjects v2を取得せずpublic Issueのdegraded modeで表示しています。"
            )
            nodes = self._load_rest_issues(diagnostics)

        for node in nodes:
            node.apply_compatibility_relations()
        self._reconcile_children(nodes)

        project_title: str | None = None
        if self.config.token:
            try:
                project_title, fields = self._load_project_fields()
                if fields:
                    nodes = self._scope_to_project(nodes, set(fields))
                self._apply_project_fields(nodes, fields)
            except GitHubApiError as error:
                degraded = True
                diagnostics.append(f"Projects v2取得失敗: {error.public_message}")

        edges = build_edges(nodes)
        nodes.sort(key=lambda node: node.number)
        return {
            "repository": f"{self.config.owner}/{self.config.repository}",
            "project": {
                "owner": self.config.owner,
                "number": self.config.project_number,
                "title": project_title,
            },
            "degraded": degraded,
            "diagnostics": diagnostics,
            "nodes": [node.to_dict() for node in nodes],
            "edges": [edge.to_dict() for edge in edges],
        }

    def _load_graphql_issues(self) -> list[IssueNode]:
        cursor: str | None = None
        nodes: list[IssueNode] = []
        while True:
            data = self._graphql(
                _REPOSITORY_ISSUES_QUERY,
                {
                    "owner": self.config.owner,
                    "repository": self.config.repository,
                    "cursor": cursor,
                },
            )
            repository = data.get("repository")
            if not isinstance(repository, dict):
                raise GitHubApiError("repository not found")
            connection = repository.get("issues") or {}
            for raw in connection.get("nodes") or []:
                if not isinstance(raw, dict):
                    continue
                parent = raw.get("parent") or {}
                sub_issues = raw.get("subIssues") or {}
                nodes.append(
                    IssueNode(
                        number=int(raw["number"]),
                        title=str(raw.get("title") or ""),
                        body=str(raw.get("body") or ""),
                        url=str(raw.get("url") or ""),
                        state=str(raw.get("state") or "OPEN"),
                        updated_at=_optional_str(raw.get("updatedAt")),
                        parent_number=_optional_int(parent.get("number")),
                        child_numbers=sorted(
                            {
                                int(item["number"])
                                for item in sub_issues.get("nodes") or []
                                if isinstance(item, dict) and item.get("number") is not None
                            }
                        ),
                    )
                )
            page_info = connection.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = _optional_str(page_info.get("endCursor"))
            if not cursor:
                break
        return nodes

    def _load_project_fields(self) -> tuple[str | None, dict[int, dict[str, Any]]]:
        cursor: str | None = None
        fields: dict[int, dict[str, Any]] = {}
        title: str | None = None
        while True:
            data = self._graphql(
                _PROJECT_QUERY,
                {
                    "owner": self.config.owner,
                    "projectNumber": self.config.project_number,
                    "cursor": cursor,
                },
            )
            user = data.get("user")
            if not isinstance(user, dict):
                raise GitHubApiError("project owner not found")
            project = user.get("projectV2")
            if not isinstance(project, dict):
                raise GitHubApiError("project not found or token lacks project read permission")
            title = _optional_str(project.get("title"))
            connection = project.get("items") or {}
            for item in connection.get("nodes") or []:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, dict) or content.get("number") is None:
                    continue
                number = int(content["number"])
                process_number = _nested_value(item, "processNumber", "number")
                process_text = _nested_value(item, "processText", "text")
                fields[number] = {
                    "project_item_id": _optional_str(item.get("id")),
                    "status": _nested_value(item, "status", "name"),
                    "issue_level": _nested_value(item, "issueLevel", "name"),
                    "work_type": _nested_value(item, "workType", "name"),
                    "area": _nested_value(item, "area", "name"),
                    "priority": _nested_value(item, "priority", "name"),
                    "process": process_number if process_number is not None else process_text,
                    "start_date": _nested_value(item, "startDate", "date"),
                    "target_date": _nested_value(item, "targetDate", "date"),
                }
            page_info = connection.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = _optional_str(page_info.get("endCursor"))
            if not cursor:
                break
        return title, fields

    def _load_rest_issues(self, diagnostics: list[str]) -> list[IssueNode]:
        page = 1
        nodes: list[IssueNode] = []
        try:
            while True:
                query = urlencode({"state": "open", "per_page": 100, "page": page})
                url = (
                    f"https://api.github.com/repos/{self.config.owner}/"
                    f"{self.config.repository}/issues?{query}"
                )
                raw = self._request_json(url)
                if not isinstance(raw, list):
                    raise GitHubApiError("unexpected REST issues response")
                issue_rows = [item for item in raw if isinstance(item, dict) and "pull_request" not in item]
                for item in issue_rows:
                    nodes.append(
                        IssueNode(
                            number=int(item["number"]),
                            title=str(item.get("title") or ""),
                            body=str(item.get("body") or ""),
                            url=str(item.get("html_url") or ""),
                            state=str(item.get("state") or "open").upper(),
                            updated_at=_optional_str(item.get("updated_at")),
                        )
                    )
                if len(raw) < 100:
                    break
                page += 1
        except GitHubApiError as error:
            diagnostics.append(f"REST Issue取得失敗: {error.public_message}")
            if not nodes:
                raise
        return nodes

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.config.token:
            raise GitHubApiError("GitHub token is not configured")
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        request = Request(
            "https://api.github.com/graphql",
            data=body,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "User-Agent": "yura-issue-graph",
            },
        )
        payload = self._execute(request)
        if not isinstance(payload, dict):
            raise GitHubApiError("unexpected GraphQL response")
        errors = payload.get("errors")
        if errors:
            first = errors[0] if isinstance(errors, list) and errors else {}
            message = first.get("message") if isinstance(first, dict) else None
            raise GitHubApiError(str(message or "GraphQL request failed"))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise GitHubApiError("GraphQL response does not contain data")
        return data

    def _request_json(self, url: str) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "yura-issue-graph",
        }
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        return self._execute(Request(url, headers=headers))

    def _execute(self, request: Request) -> Any:
        if self.transport is not None:
            return self.transport(request)
        try:
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise GitHubApiError(f"GitHub API returned HTTP {error.code}") from error
        except URLError as error:
            raise GitHubApiError("GitHub API is unreachable") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GitHubApiError("GitHub API returned invalid JSON") from error

    @staticmethod
    def _reconcile_children(nodes: list[IssueNode]) -> None:
        by_number = {node.number: node for node in nodes}
        for node in nodes:
            if node.parent_number in by_number:
                parent = by_number[int(node.parent_number)]
                if node.number not in parent.child_numbers:
                    parent.child_numbers.append(node.number)
                    parent.child_numbers.sort()
            for child_number in list(node.child_numbers):
                child = by_number.get(child_number)
                if child is not None and child.parent_number is None:
                    child.parent_number = node.number

    @staticmethod
    def _scope_to_project(nodes: list[IssueNode], project_numbers: set[int]) -> list[IssueNode]:
        by_number = {node.number: node for node in nodes}
        included = {number for number in project_numbers if number in by_number}
        queue = list(included)
        while queue:
            number = queue.pop()
            node = by_number.get(number)
            if node is None:
                continue
            related = set(node.child_numbers) | set(node.dependency_numbers)
            if node.parent_number is not None:
                related.add(node.parent_number)
            for other in related:
                if other in by_number and other not in included:
                    included.add(other)
                    queue.append(other)
        return [node for node in nodes if node.number in included]

    @staticmethod
    def _apply_project_fields(nodes: list[IssueNode], fields: dict[int, dict[str, Any]]) -> None:
        for node in nodes:
            values = fields.get(node.number)
            if not values:
                continue
            node.project_item_id = values.get("project_item_id")
            node.status = values.get("status")
            node.issue_level = values.get("issue_level") or node.issue_level
            node.work_type = values.get("work_type")
            node.area = values.get("area")
            node.priority = values.get("priority")
            node.process = values.get("process")
            node.start_date = values.get("start_date")
            node.target_date = values.get("target_date")


class GitHubApiError(RuntimeError):
    def __init__(self, public_message: str) -> None:
        super().__init__(public_message)
        self.public_message = public_message[:300]


def _nested_value(item: dict[str, Any], key: str, value_key: str) -> Any:
    value = item.get(key)
    if not isinstance(value, dict):
        return None
    return value.get(value_key)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
