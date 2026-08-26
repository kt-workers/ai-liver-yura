#!/usr/bin/env python3
"""Host launcher using injected GitHub credentials only."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))


def main() -> int:
    from app.operations.host_launcher import (
        EnvironmentSecretProvider,
        GitHubCredentialUnavailable,
        build_launch_environment,
        launch_vscode,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    try:
        environment = build_launch_environment(
            root, EnvironmentSecretProvider(os.environ), os.environ
        )
    except GitHubCredentialUnavailable:
        print('{"reason":"GITHUB_CREDENTIAL_UNAVAILABLE","review_status":"NOT_RUN"}')
        return 0
    if args.preflight:
        return subprocess.run(
            (sys.executable, "-m", "app.operations.preflight"),
            cwd=root,
            env=dict(environment.values),
            check=False,
        ).returncode
    launch_vscode(root, environment)
    return 0


raise SystemExit(main())
