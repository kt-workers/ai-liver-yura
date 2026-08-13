from __future__ import annotations

from typing import Any

from tools.independent_review.github_client import GitHubClient


class PagingGitHubClient(GitHubClient):
    def __init__(self) -> None:
        super().__init__("o/r", "token", "https://example.invalid")
        self.paths: list[str] = []

    def _json(
        self, method: str, path: str, *, data: dict[str, Any] | None = None
    ) -> Any:
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
