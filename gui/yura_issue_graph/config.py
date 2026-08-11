from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IssueGraphConfig:
    owner: str = "ktan514"
    repository: str = "ai-liver-yura"
    project_number: int = 6
    token: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls) -> "IssueGraphConfig":
        owner = os.getenv("YURA_ISSUE_GRAPH_OWNER", "ktan514").strip() or "ktan514"
        repository = (
            os.getenv("YURA_ISSUE_GRAPH_REPOSITORY", "ai-liver-yura").strip()
            or "ai-liver-yura"
        )
        project_number = _positive_int_env("YURA_ISSUE_GRAPH_PROJECT_NUMBER", 6)
        port = _positive_int_env("PORT", 8000)
        host = os.getenv("YURA_ISSUE_GRAPH_HOST", "127.0.0.1").strip() or "127.0.0.1"
        token = os.getenv("GITHUB_TOKEN")
        if token is not None:
            token = token.strip() or None
        return cls(
            owner=owner,
            repository=repository,
            project_number=project_number,
            token=token,
            host=host,
            port=port,
        )


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value
