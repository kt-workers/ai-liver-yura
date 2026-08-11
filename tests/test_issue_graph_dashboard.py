from __future__ import annotations

from gui.yura_issue_graph.config import IssueGraphConfig
from gui.yura_issue_graph.github_client import IssueGraphService
from gui.yura_issue_graph.models import (
    IssueNode,
    build_edges,
    extract_dependency_numbers,
    extract_issue_level,
    extract_parent_number,
    extract_related_pr_numbers,
)
from gui.yura_issue_graph.server import app, health


def test_compatibility_relationship_extractors() -> None:
    body = """
## Issueレベル
**Work**
Parent: #225
Depends on: #226, #227
Related: PR #219 / Draft PR #233
"""
    assert extract_parent_number(body) == 225
    assert extract_dependency_numbers(body, 229) == [226, 227]
    assert extract_related_pr_numbers(body) == [219, 233]
    assert extract_issue_level(body) == "Work"


def test_build_edges_separates_parent_and_dependency() -> None:
    parent = IssueNode(225, "parent", "", "u", "OPEN", child_numbers=[226])
    child = IssueNode(226, "child", "", "u", "OPEN", parent_number=225)
    dependent = IssueNode(227, "dependent", "", "u", "OPEN", dependency_numbers=[226])
    edges = {(edge.source, edge.target, edge.kind) for edge in build_edges([parent, child, dependent])}
    assert edges == {(225, 226, "parent"), (226, 227, "dependency")}


def test_project_fields_are_joined_without_overwriting_compat_issue_level() -> None:
    node = IssueNode(10, "x", "Issueレベル: Work", "u", "OPEN")
    node.apply_compatibility_relations()
    IssueGraphService._apply_project_fields(
        [node],
        {
            10: {
                "project_item_id": "PVTI_x",
                "status": "Verification",
                "issue_level": None,
                "work_type": "検証",
                "area": "GUI",
                "priority": "Medium",
                "process": 80.0,
                "start_date": "2026-08-11",
                "target_date": "2026-08-12",
            }
        },
    )
    assert node.issue_level == "Work"
    assert node.status == "Verification"
    assert node.area == "GUI"
    assert node.process == 80.0


def test_rest_degraded_mode_does_not_require_token() -> None:
    responses = iter(
        [
            [
                {
                    "number": 2,
                    "title": "child",
                    "body": "Parent: #1\nDepends on: #3",
                    "html_url": "https://github.com/o/r/issues/2",
                    "state": "open",
                    "updated_at": "2026-08-11T00:00:00Z",
                },
                {
                    "number": 1,
                    "title": "parent",
                    "body": "Issueレベル: Parent",
                    "html_url": "https://github.com/o/r/issues/1",
                    "state": "open",
                    "updated_at": "2026-08-11T00:00:00Z",
                },
                {
                    "number": 3,
                    "title": "dependency",
                    "body": "",
                    "html_url": "https://github.com/o/r/issues/3",
                    "state": "closed",
                    "updated_at": "2026-08-11T00:00:00Z",
                },
            ]
        ]
    )

    def transport(_request):
        return next(responses)

    service = IssueGraphService(IssueGraphConfig(owner="o", repository="r", token=None), transport=transport)
    payload = service.load_graph()
    assert payload["degraded"] is True
    assert any("GITHUB_TOKEN" in message for message in payload["diagnostics"])
    assert {tuple((e["source"], e["target"], e["kind"])) for e in payload["edges"]} == {
        (1, 2, "parent"),
        (3, 2, "dependency"),
    }


def test_health_and_routes_exist() -> None:
    assert health() == {"status": "ok", "service": "yura-issue-graph"}
    paths = {route.path for route in app.routes}
    assert "/" in paths
    assert "/api/health" in paths
    assert "/api/graph" in paths


def test_project_scope_keeps_related_context() -> None:
    parent = IssueNode(1, "parent", "", "u", "OPEN", child_numbers=[2])
    work = IssueNode(2, "work", "", "u", "OPEN", parent_number=1, dependency_numbers=[3])
    dependency = IssueNode(3, "dep", "", "u", "OPEN")
    unrelated = IssueNode(99, "unrelated", "", "u", "OPEN")
    scoped = IssueGraphService._scope_to_project([parent, work, dependency, unrelated], {2})
    assert {node.number for node in scoped} == {1, 2, 3}
