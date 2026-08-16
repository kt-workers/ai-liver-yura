from __future__ import annotations

from typing import Any

import pytest

from tools.independent_review.github_client import GitHubApiError, GitHubClient


class PagingGitHubClient(GitHubClient):
    def __init__(self) -> None:
        super().__init__("o/r", "token", "https://example.invalid")
        self.paths: list[str] = []

    def _json(self, method: str, path: str, *, data: dict[str, Any] | None = None) -> Any:
        self.paths.append(path)
        if path.endswith("&page=1"):
            return [{"id": index} for index in range(100)]
        return [{"id": 100}]


def test_list_reviews_fetches_all_pages() -> None:
    client = PagingGitHubClient()
    reviews = client.list_reviews(7)
    assert len(reviews) == 101
    assert client.paths == [
        "/repos/o/r/pulls/7/reviews?per_page=100&page=1",
        "/repos/o/r/pulls/7/reviews?per_page=100&page=2",
    ]


def test_get_pull_diff_uses_fixed_base_and_head_shas() -> None:
    class DiffGitHubClient(GitHubClient):
        def __init__(self) -> None:
            super().__init__("o/r", "token", "https://example.invalid")
            self.path: str | None = None
            self.accept: str | None = None

        def _request(
            self,
            method: str,
            path: str,
            *,
            accept: str = "application/vnd.github+json",
            data: dict[str, Any] | None = None,
        ) -> tuple[bytes, dict[str, str]]:
            self.path = path
            self.accept = accept
            return "固定差分".encode(), {}

    client = DiffGitHubClient()
    diff = client.get_pull_diff("a" * 40, "b" * 40)
    assert diff == "固定差分"
    assert client.path == "/repos/o/r/compare/" + "a" * 40 + "..." + "b" * 40
    assert client.accept == "application/vnd.github.v3.diff"


@pytest.mark.parametrize("response", [[], {"workflow_runs": {}}, {}])
def test_malformed_workflow_runs_response_is_rejected(response: object) -> None:
    class MalformedWorkflowRunsClient(GitHubClient):
        def _json(self, method: str, path: str, *, data: dict[str, Any] | None = None) -> Any:
            return response

    client = MalformedWorkflowRunsClient("o/r", "token", "https://example.invalid")
    with pytest.raises(GitHubApiError, match="workflow run一覧"):
        client.list_workflow_runs_for_head("a" * 40)


class WorkflowPagingGitHubClient(GitHubClient):
    def __init__(self) -> None:
        super().__init__("o/r", "token", "https://example.invalid")
        self.paths: list[str] = []

    def _json(self, method: str, path: str, *, data: dict[str, Any] | None = None) -> Any:
        self.paths.append(path)
        if path.endswith("&page=1"):
            return {"workflow_runs": [{"id": index} for index in range(100)]}
        return {"workflow_runs": [{"id": 100}]}


def test_list_workflow_runs_fetches_all_pages() -> None:
    client = WorkflowPagingGitHubClient()
    runs = client.list_workflow_runs_for_head("a" * 40)

    assert len(runs) == 101
    assert client.paths == [
        "/repos/o/r/actions/runs?head_sha=" + "a" * 40 + "&per_page=100&page=1",
        "/repos/o/r/actions/runs?head_sha=" + "a" * 40 + "&per_page=100&page=2",
    ]


def test_non_mapping_workflow_run_is_rejected() -> None:
    class InvalidElementClient(GitHubClient):
        def _json(self, method: str, path: str, *, data: dict[str, Any] | None = None) -> Any:
            return {"workflow_runs": [{"id": 1}, "invalid"]}

    client = InvalidElementClient("o/r", "token", "https://example.invalid")
    with pytest.raises(GitHubApiError, match="workflow run一覧"):
        client.list_workflow_runs_for_head("a" * 40)
