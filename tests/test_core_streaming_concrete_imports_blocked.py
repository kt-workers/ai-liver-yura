from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_core_imports_when_streaming_implementations_and_sdks_are_blocked() -> None:
    script = """
import builtins
original = builtins.__import__
blocked_prefixes = (
    'subsystems.streaming',
    'googleapiclient',
    'google_auth',
    'google_auth_oauthlib',
    'obsws',
    'obswebsocket',
    '.'.join(('app', 'plugins', 'youtube_streaming')),
    '.'.join(('app', 'adapters', 'streaming')),
)
def blocked(name, *args, **kwargs):
    if any(name == prefix or name.startswith(prefix + '.') for prefix in blocked_prefixes):
        raise ModuleNotFoundError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
import app
import app.__main__
import app.integrations.streaming
from app.bootstrap.runtime import create_runtime_coordinator
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
