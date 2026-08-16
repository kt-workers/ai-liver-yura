from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class GitHubApiError(RuntimeError):
    pass


class GitHubClient:
    def __init__(
        self, repository: str, token: str, api_url: str = "https://api.github.com"
    ) -> None:
        self.repository = repository
        self.token = token
        self.api_url = api_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        *,
        accept: str = "application/vnd.github+json",
        data: dict[str, Any] | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        body = json.dumps(data).encode("utf-8") if data is not None else None
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2026-03-10",
                "Content-Type": "application/json",
                "User-Agent": "yura-independent-ai-review",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")[:1000]
            raise GitHubApiError(
                f"GitHub API要求に失敗しました: {method} {path} / {exc.code} / {payload}"
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubApiError(
                f"GitHub API接続に失敗しました: {method} {path} / {exc.reason}"
            ) from exc

    def _json(self, method: str, path: str, *, data: dict[str, Any] | None = None) -> Any:
        raw, _ = self._request(method, path, data=data)
        return json.loads(raw.decode("utf-8"))

    def get_pull(self, pr_number: int) -> dict[str, object]:
        result = self._json("GET", f"/repos/{self.repository}/pulls/{pr_number}")
        if not isinstance(result, dict):
            raise GitHubApiError("PR情報の応答形式が不正です")
        return result

    def get_pull_diff(self, pr_number: int) -> str:
        raw, _ = self._request(
            "GET",
            f"/repos/{self.repository}/pulls/{pr_number}",
            accept="application/vnd.github.v3.diff",
        )
        return raw.decode("utf-8", errors="replace")

    def get_issue(self, issue_number: int) -> dict[str, object]:
        result = self._json("GET", f"/repos/{self.repository}/issues/{issue_number}")
        if not isinstance(result, dict):
            raise GitHubApiError("Issue情報の応答形式が不正です")
        return result

    def get_content(self, path: str, ref: str) -> str:
        encoded_path = urllib.parse.quote(path, safe="/")
        encoded_ref = urllib.parse.quote(ref, safe="")
        result = self._json(
            "GET", f"/repos/{self.repository}/contents/{encoded_path}?ref={encoded_ref}"
        )
        if not isinstance(result, dict) or result.get("encoding") != "base64":
            raise GitHubApiError(f"ファイル取得結果が不正です: {path}@{ref}")
        content = result.get("content")
        if not isinstance(content, str):
            raise GitHubApiError(f"ファイル内容が存在しません: {path}@{ref}")
        return base64.b64decode(content).decode("utf-8")

    def list_workflow_runs_for_head(self, head_sha: str) -> list[dict[str, object]]:
        query = urllib.parse.urlencode({"head_sha": head_sha, "per_page": 50})
        result = self._json("GET", f"/repos/{self.repository}/actions/runs?{query}")
        if not isinstance(result, dict):
            raise GitHubApiError("workflow run一覧の応答形式が不正です")
        runs = result.get("workflow_runs")
        if not isinstance(runs, list):
            raise GitHubApiError("workflow run一覧が存在しないか形式が不正です")
        return [item for item in runs if isinstance(item, dict)]

    def list_reviews(self, pr_number: int) -> list[dict[str, object]]:
        reviews: list[dict[str, object]] = []
        page = 1
        while True:
            result = self._json(
                "GET",
                f"/repos/{self.repository}/pulls/{pr_number}/reviews?per_page=100&page={page}",
            )
            if not isinstance(result, list):
                raise GitHubApiError("レビュー一覧の応答形式が不正です")
            reviews.extend(item for item in result if isinstance(item, dict))
            if len(result) < 100:
                return reviews
            page += 1

    def create_commit_status(
        self,
        sha: str,
        *,
        state: str,
        context: str,
        description: str,
        target_url: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "state": state,
            "context": context,
            "description": description[:140],
        }
        if target_url:
            payload["target_url"] = target_url
        self._json("POST", f"/repos/{self.repository}/statuses/{sha}", data=payload)

    def create_review_comment(self, pr_number: int, commit_id: str, body: str) -> None:
        self._json(
            "POST",
            f"/repos/{self.repository}/pulls/{pr_number}/reviews",
            data={"commit_id": commit_id, "body": body, "event": "COMMENT"},
        )
