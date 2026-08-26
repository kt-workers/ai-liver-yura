from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SecretProvider(Protocol):
    def github_token(self) -> str: ...

    def reviewer_api_key(self) -> str: ...


class ReviewerCredentialUnavailable(RuntimeError):
    """The dedicated reviewer credential is intentionally unavailable."""


class GitHubCredentialUnavailable(RuntimeError):
    """The GitHub credential is intentionally unavailable."""


class EnvironmentSecretProvider:
    """Reads credentials already injected into the host process environment."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = values

    def github_token(self) -> str:
        try:
            return self._required("GH_TOKEN", "GitHub credential unavailable")
        except RuntimeError as error:
            raise GitHubCredentialUnavailable(str(error)) from error

    def reviewer_api_key(self) -> str:
        try:
            return self._required("OPENAI_API_KEY_REVIEWER", "Reviewer credential unavailable")
        except RuntimeError as error:
            raise ReviewerCredentialUnavailable(str(error)) from error

    def _required(self, name: str, message: str) -> str:
        value = self._values.get(name, "")
        if not value:
            raise RuntimeError(message)
        return value


@dataclass(frozen=True, slots=True)
class LaunchEnvironment:
    values: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ReviewerLaunchEnvironment:
    values: Mapping[str, str]


def build_launch_environment(
    root: Path, secrets: SecretProvider, parent: Mapping[str, str]
) -> LaunchEnvironment:
    goal = root / "docs" / "operations" / "loop_mission_goal.md"
    content = goal.read_bytes()
    lines = content.decode("utf-8").splitlines()
    version = next(line.removeprefix("version: ") for line in lines if line.startswith("version: "))
    generation = next(
        line.removeprefix("generation: ") for line in lines if line.startswith("generation: ")
    )
    path = parent.get("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
    return LaunchEnvironment(
        {
            "PATH": path,
            "GH_TOKEN": secrets.github_token(),
            "CODEX_MISSION_GOAL_VERSION": version,
            "CODEX_MISSION_GOAL_GENERATION": generation,
            "CODEX_MISSION_GOAL_SHA256": hashlib.sha256(content).hexdigest(),
        }
    )


def build_reviewer_environment(
    root: Path, secrets: SecretProvider, parent: Mapping[str, str]
) -> ReviewerLaunchEnvironment:
    """Build the minimal environment for the independent reviewer child only."""
    config = root / "docs" / "operations" / "reviewer_config.json"
    try:
        model = json.loads(config.read_text(encoding="utf-8"))["default_model"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("Reviewer configuration unavailable") from error
    if not isinstance(model, str) or not model:
        raise RuntimeError("Reviewer configuration unavailable")
    return ReviewerLaunchEnvironment(
        {
            "PATH": parent.get("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"),
            "OPENAI_API_KEY": secrets.reviewer_api_key(),
            "OPENAI_REVIEWER_MODEL": model,
            "OPENAI_REVIEWER_CONFIG": str(config),
        }
    )


def launch_vscode(root: Path, environment: LaunchEnvironment) -> None:
    subprocess.run(("code", str(root)), check=True, env=dict(environment.values), timeout=30)


def run_reviewer_subprocess(
    root: Path, environment: ReviewerLaunchEnvironment, context: Mapping[str, object]
) -> subprocess.CompletedProcess[str]:
    """Run a reviewer with no GitHub, database, or inherited parent secrets."""
    return subprocess.run(
        (sys.executable, "-m", "app.operations.canonical_reviewer"),
        check=False,
        cwd=root,
        env=dict(environment.values),
        input=json.dumps(context, ensure_ascii=False),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=90,
    )
