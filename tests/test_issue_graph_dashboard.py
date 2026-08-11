from __future__ import annotations

import inspect
import json
from pathlib import Path

import yaml

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
from gui.yura_issue_graph.server import app, graph, health


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

    service = IssueGraphService(
        IssueGraphConfig(owner="o", repository="r", token=None),
        transport=transport,
    )
    payload = service.load_graph()
    assert payload["include_closed"] is False
    assert payload["degraded"] is True
    assert any("GITHUB_TOKEN" in message for message in payload["diagnostics"])
    assert {tuple((e["source"], e["target"], e["kind"])) for e in payload["edges"]} == {
        (1, 2, "parent"),
        (3, 2, "dependency"),
    }


def test_graphql_issue_state_scope_switches_between_open_and_all_states() -> None:
    captured_states: list[list[str]] = []

    def transport(request):
        payload = json.loads(request.data.decode("utf-8"))
        captured_states.append(payload["variables"]["states"])
        return {
            "data": {
                "repository": {
                    "issues": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }

    service = IssueGraphService(
        IssueGraphConfig(owner="o", repository="r", token="token"),
        transport=transport,
    )
    service._load_graphql_issues(include_closed=False)
    service._load_graphql_issues(include_closed=True)

    assert captured_states == [["OPEN"], ["OPEN", "CLOSED"]]


def test_rest_issue_state_scope_switches_between_open_and_all() -> None:
    urls: list[str] = []

    def transport(request):
        urls.append(request.full_url)
        return []

    service = IssueGraphService(
        IssueGraphConfig(owner="o", repository="r", token=None),
        transport=transport,
    )
    service._load_rest_issues([], include_closed=False)
    service._load_rest_issues([], include_closed=True)

    assert "state=open" in urls[0]
    assert "state=all" in urls[1]


def test_health_and_routes_exist() -> None:
    assert health() == {"status": "ok", "service": "yura-issue-graph"}
    paths = {route.path for route in app.routes}
    assert "/" in paths
    assert "/api/health" in paths
    assert "/api/graph" in paths
    assert inspect.signature(graph).parameters["include_closed"].default is False


def test_project_scope_keeps_related_context() -> None:
    parent = IssueNode(1, "parent", "", "u", "OPEN", child_numbers=[2])
    work = IssueNode(2, "work", "", "u", "OPEN", parent_number=1, dependency_numbers=[3])
    dependency = IssueNode(3, "dep", "", "u", "OPEN")
    unrelated = IssueNode(99, "unrelated", "", "u", "OPEN")
    scoped = IssueGraphService._scope_to_project([parent, work, dependency, unrelated], {2})
    assert {node.number for node in scoped} == {1, 2, 3}


def test_render_blueprint_preserves_existing_services_and_adds_issue_graph() -> None:
    blueprint = yaml.safe_load(Path("render.yaml").read_text(encoding="utf-8"))
    services = {service["name"]: service for service in blueprint["services"]}

    assert {
        "yura-inner-state-visualizer",
        "yura-configuration-harbor",
        "yura-avatar-runtime-lab",
        "yura-issue-graph",
    }.issubset(services)

    issue_graph = services["yura-issue-graph"]
    assert issue_graph["type"] == "web"
    assert issue_graph["runtime"] == "python"
    assert issue_graph["plan"] == "free"
    assert issue_graph["branch"] == "feature/issue-graph-dashboard"
    assert issue_graph["healthCheckPath"] == "/api/health"
    assert issue_graph["autoDeployTrigger"] == "commit"
    assert "gui.yura_issue_graph.server:app" in issue_graph["startCommand"]
    assert "$PORT" in issue_graph["startCommand"]

    env_vars = {item["key"]: item for item in issue_graph["envVars"]}
    token = env_vars["GITHUB_TOKEN"]
    assert token["sync"] is False
    assert "value" not in token
    assert env_vars["YURA_ISSUE_GRAPH_OWNER"]["value"] == "ktan514"
    assert env_vars["YURA_ISSUE_GRAPH_REPOSITORY"]["value"] == "ai-liver-yura"
    assert env_vars["YURA_ISSUE_GRAPH_PROJECT_NUMBER"]["value"] == "6"


def test_browser_uses_hierarchical_component_packing_not_force_relaxation() -> None:
    html = Path("gui/yura_issue_graph/static/index.html").read_text(encoding="utf-8")

    assert "function buildForest(" in html
    assert "function layoutComponent(" in html
    assert "function packHierarchy(" in html
    assert "subtreeSpan" in html
    assert "relaxFreeLayout" not in html
    assert "jitterX" not in html


def test_browser_separates_parent_trees_and_unlinked_issues_visually() -> None:
    html = Path("gui/yura_issue_graph/static/index.html").read_text(encoding="utf-8")

    assert 'id="groups"' in html
    assert "function renderGroups(" in html
    assert "component-frame" in html
    assert "親子ツリー #" in html
    assert "親子関係なし（" in html
    assert "component.hasHierarchy" in html
    assert "!component.hasHierarchy" in html


def test_browser_routes_parent_edges_by_bus_and_dependencies_around_measured_nodes() -> None:
    html = Path("gui/yura_issue_graph/static/index.html").read_text(encoding="utf-8")

    assert "function parentBusRoute(" in html
    assert "function measuredRects(" in html
    assert "el.offsetWidth" in html
    assert "el.offsetHeight" in html
    assert "function routeByVisibility(" in html
    assert "function routeDependency(" in html
    assert "function pathIsClear(" in html
    assert "fallbackBezier" not in html
    assert "edge.source===state.selected" in html
    assert ".edge.focused" in html
    assert ".edge.dimmed" in html


def test_dependency_edges_are_contextual_by_default_and_can_be_shown_all() -> None:
    html = Path("gui/yura_issue_graph/static/index.html").read_text(encoding="utf-8")

    assert 'id="showDependencies"' in html
    assert "依存線を全表示" in html
    assert "function dependencyShouldBeVisible(" in html
    assert "showDependencies.checked" in html
    assert "edge.source===state.selected||edge.target===state.selected" in html
    assert "showDependencies.addEventListener('change',drawEdges)" in html


def test_dependency_arrow_uses_fixed_marker_and_straight_port_leads() -> None:
    html = Path("gui/yura_issue_graph/static/index.html").read_text(encoding="utf-8")

    assert "PORT_LEAD=30" in html
    assert "function dependencyPortCandidates(" in html
    assert "sourceLead" in html
    assert "targetLead" in html
    assert 'markerUnits="userSpaceOnUse"' in html
    assert 'markerWidth="7"' in html
    assert 'markerHeight="7"' in html
    assert "arrowFocus" not in html
    assert "path.setAttribute('marker-end','url(#arrowSmall)')" in html


def test_collapse_keeps_parent_expand_control_and_tree_identity() -> None:
    html = Path("gui/yura_issue_graph/static/index.html").read_text(encoding="utf-8")

    assert "hierarchyCandidates:new Set()" in html
    assert "state.hierarchyCandidates=filteredVisibleSet(map)" in html
    assert "hideCollapsedDescendants(state.hierarchyCandidates,map)" in html
    assert "function hasExpandableChildren(" in html
    assert "state.collapsed.has(node.number)" in html
    assert "button.textContent=state.collapsed.has(number)?'+':'−'" in html
    assert "function toggleCollapse(" in html
    assert "screenX=before?state.tx+" in html
    assert "screenY=before?state.ty+" in html
    assert "hasHierarchy=positions.size>1" in html
    assert "node.child_numbers||[]" in html


def test_selected_node_focus_dims_unrelated_nodes() -> None:
    html = Path("gui/yura_issue_graph/static/index.html").read_text(encoding="utf-8")

    assert ".node.context-dim" in html
    assert "function directRelatedNumbers(" in html
    assert "function updateNodeFocus(" in html
    assert "related&&!related.has(number)" in html


def test_initial_view_keeps_readable_scale_before_full_fit() -> None:
    html = Path("gui/yura_issue_graph/static/index.html").read_text(encoding="utf-8")

    assert "MIN_READABLE_SCALE=.65" in html
    assert "function setInitialViewport(" in html
    assert "if(fit>=MIN_READABLE_SCALE)" in html
    assert "state.scale=MIN_READABLE_SCALE" in html
    assert "document.getElementById('reset').addEventListener('click',fitToView)" in html


def test_browser_closed_issue_switch_requests_server_side_state_scope() -> None:
    html = Path("gui/yura_issue_graph/static/index.html").read_text(encoding="utf-8")

    assert 'id="includeClosed"' in html
    assert "include_closed=${includeClosedValue?'true':'false'}" in html
    assert "includeClosed.addEventListener('change',load)" in html
    assert "Closedも表示" in html
