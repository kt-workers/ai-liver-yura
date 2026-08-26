#!/usr/bin/env python3
"""Host-side launcher: Keychain -> ephemeral environment -> VS Code."""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))


def main() -> int:
    from app.operations.host_launcher import (
        MacOSKeychainSecretProvider,
        build_launch_environment,
        launch_vscode,
    )

    environment = build_launch_environment(
        root, MacOSKeychainSecretProvider(), __import__("os").environ
    )
    if sys.argv[1:] == ["--preflight"]:
        return subprocess.run(
            (sys.executable, "-m", "app.operations.preflight"),
            cwd=root,
            env=dict(environment.values),
            check=False,
        ).returncode
    launch_vscode(root, environment)
    return 0


raise SystemExit(main())
