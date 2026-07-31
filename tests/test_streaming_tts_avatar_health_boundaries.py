from __future__ import annotations

import ast
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.integrations.streaming import (
    DependencyKind,
    DependencyState,
    StreamingCapability,
    StreamingDependencyHealth,
)
from subsystems.streaming import build_streaming_subsystem
from subsystems.streaming.adapters.dependency_health import (
    StaticDependencyHealthProvider,
)
from subsystems.streaming.adapters.fake_runtime import FakeStreamingRuntime
from subsystems.streaming.api import StreamingSubsystemApi
from subsystems.streaming.application import StreamingSubsystemService

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _ready(
    kind: DependencyKind,
    capability: StreamingCapability,
) -> StaticDependencyHealthProvider:
    return StaticDependencyHealthProvider(
        StreamingDependencyHealth(
            kind=kind,
            state=DependencyState.READY,
            healthy=True,
            available=True,
            checked_at=NOW,
            capabilities=frozenset({capability}),
        )
    )


def test_dependency_health_implementation_has_no_core_or_sdk_dependency() -> None:
    application = (
        ROOT / "subsystems" / "streaming" / "application" / "dependency_health.py"
    )
    adapter_root = (
        ROOT / "subsystems" / "streaming" / "adapters" / "dependency_health"
    )
    paths = [application, *sorted(adapter_root.rglob("*.py"))]
    forbidden = (
        "app.adapters.tts",
        "app.adapters.live2d",
        "app.bootstrap",
        "app.runtime",
        "app.services",
        "gui",
    )
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {name}"
        for path in paths
        for name in _imports(path)
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    )

    assert violations == []


def test_subsystem_import_and_build_do_not_load_tts_or_live2d_adapters() -> None:
    script = """
import builtins
original_import = builtins.__import__
def blocked_import(name, *args, **kwargs):
    if name.startswith(("app.adapters.tts", "app.adapters.live2d")):
        raise ModuleNotFoundError(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = blocked_import
import subsystems.streaming
subsystems.streaming.build_streaming_subsystem()
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


@pytest.mark.asyncio
async def test_dependency_queries_health_and_capabilities_are_consistent() -> None:
    api = build_streaming_subsystem(
        clock=lambda: NOW,
        dependency_health_providers=(
            _ready(DependencyKind.TTS, StreamingCapability.TTS_AVAILABLE),
            _ready(DependencyKind.AVATAR, StreamingCapability.AVATAR_AVAILABLE),
        ),
    )

    values = await api.list_dependency_health()
    tts = await api.get_dependency_health(DependencyKind.TTS)
    health = await api.get_health()
    capabilities = await api.get_capabilities()

    assert values == (
        await api.get_dependency_health(DependencyKind.TTS),
        await api.get_dependency_health(DependencyKind.AVATAR),
    )
    assert tts.state is DependencyState.READY
    assert health.healthy is True
    assert health.components["tts"] is True
    assert health.components["avatar"] is True
    assert StreamingCapability.TTS_AVAILABLE in capabilities.values
    assert StreamingCapability.AVATAR_AVAILABLE in capabilities.values


@pytest.mark.asyncio
async def test_unconnected_dependencies_do_not_make_subsystem_unhealthy() -> None:
    api = build_streaming_subsystem(clock=lambda: NOW)

    values = await api.list_dependency_health()
    health = await api.get_health()
    capabilities = await api.get_capabilities()

    assert tuple(value.state for value in values) == (
        DependencyState.DISCONNECTED,
        DependencyState.DISCONNECTED,
    )
    assert health.healthy is True
    assert health.components["tts"] is False
    assert health.components["avatar"] is False
    assert StreamingCapability.TTS_AVAILABLE not in capabilities.values
    assert StreamingCapability.AVATAR_AVAILABLE not in capabilities.values


@pytest.mark.asyncio
async def test_dependency_health_queries_work_without_youtube_or_obs_bundles() -> None:
    api = StreamingSubsystemApi(
        StreamingSubsystemService(FakeStreamingRuntime(clock=lambda: NOW))
    )

    values = await api.list_dependency_health()
    health = await api.get_health()

    assert len(values) == 2
    assert health.healthy is True
    assert health.components == {
        "runtime": True,
        "obs": True,
        "youtube": True,
        "tts": False,
        "avatar": False,
    }
