from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SecretProvider(Protocol):
    def github_token(self) -> str: ...


class MacOSKeychainSecretProvider:
    """Reads the token only into the child process environment; never prints it."""

    def github_token(self) -> str:
        result = subprocess.run(
            (
                "security",
                "find-generic-password",
                "-a",
                os.environ["USER"],
                "-s",
                "yura-codex-github",
                "-w",
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        token = result.stdout.strip()
        if not token:
            raise RuntimeError("GitHub credential unavailable")
        return token


@dataclass(frozen=True, slots=True)
class LaunchEnvironment:
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


def launch_vscode(root: Path, environment: LaunchEnvironment) -> None:
    subprocess.run(("code", str(root)), check=True, env=dict(environment.values), timeout=30)
