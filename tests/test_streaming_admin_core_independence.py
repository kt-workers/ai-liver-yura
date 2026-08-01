import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_admin_factory_imports_when_core_packages_are_blocked() -> None:
    script = """
import builtins
original = builtins.__import__
def blocked(name, *args, **kwargs):
    forbidden = ('app.admin_api', 'app.runtime', '.'.join(('app', 'bootstrap', 'streaming')))
    if any(name == value or name.startswith(value + '.') for value in forbidden):
        raise ModuleNotFoundError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
from subsystems.streaming.admin_api import create_streaming_admin_api
from subsystems.streaming.bootstrap import build_streaming_subsystem
create_streaming_admin_api(build_streaming_subsystem())
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


def test_gui_client_has_no_core_package_dependency() -> None:
    path = ROOT / "gui/yura-streaming-admin/client/streaming_subsystem_api_client.py"
    source = path.read_text()
    assert "app.admin_api" not in source
    assert "app.runtime" not in source
    assert "subsystems.streaming" not in source
