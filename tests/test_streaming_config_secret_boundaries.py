from __future__ import annotations

import ast
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config.app_config import load_app_config
from app.config.streaming_compat import streaming_subsystem_config_from_app_config
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
from subsystems.streaming.config import (
    NullSecretProvider,
    ObsAdapterMode,
    ObsSubsystemConfig,
    StaticSecretProvider,
    StreamingSubsystemConfig,
    YouTubeAdapterMode,
    YouTubeSubsystemConfig,
)

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_subsystem_config_has_no_core_gui_admin_game_or_sdk_imports() -> None:
    forbidden = (
        "app.config",
        "app.bootstrap",
        "app.runtime",
        "app.admin_api",
        "gui",
        "subsystems.games",
        "google",
        "google_auth_oauthlib",
        "googleapiclient",
        "obsws_python",
    )
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {name}"
        for path in (ROOT / "subsystems" / "streaming" / "config").rglob("*.py")
        for name in _imports(path)
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    )

    assert violations == []


def test_core_import_does_not_require_streaming_subsystem_config() -> None:
    script = """
import builtins
original_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name.startswith("subsystems.streaming"):
        raise ModuleNotFoundError(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = blocked
import app
from app.runtime.runtime_factory import StreamPreparationRuntime
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


def test_legacy_core_config_converts_one_way_without_secret_values() -> None:
    config = streaming_subsystem_config_from_app_config(load_app_config())

    assert config.youtube.mode is YouTubeAdapterMode.FAKE
    assert config.obs.mode is ObsAdapterMode.OBS_WEBSOCKET
    assert config.youtube.client_secret_path_ref == "YOUTUBE_CLIENT_SECRET_PATH"
    assert config.obs.password_ref == "OBS_WEBSOCKET_PASSWORD"
    assert "password=" not in repr(config).lower()


@pytest.mark.asyncio
async def test_composition_supports_independent_bundles_and_health_provider() -> None:
    tts = StaticDependencyHealthProvider(
        StreamingDependencyHealth(
            kind=DependencyKind.TTS,
            state=DependencyState.READY,
            healthy=True,
            available=True,
            checked_at=NOW,
            capabilities=frozenset({StreamingCapability.TTS_AVAILABLE}),
        )
    )
    api = build_streaming_subsystem(
        clock=lambda: NOW,
        config=StreamingSubsystemConfig(
            youtube=YouTubeSubsystemConfig(mode=YouTubeAdapterMode.DISABLED),
            obs=ObsSubsystemConfig(mode=ObsAdapterMode.FAKE),
        ),
        secret_provider=NullSecretProvider(),
        dependency_health_providers=(tts,),
    )

    health = await api.get_health()
    assert health.components == {
        "runtime": True,
        "obs": True,
        "youtube": False,
        "tts": True,
        "avatar": False,
    }


def test_fake_and_disabled_build_without_loading_external_sdks() -> None:
    google_modules = {
        name: value for name, value in sys.modules.items() if name.startswith("google")
    }
    obs_module = sys.modules.get("obsws_python")

    build_streaming_subsystem(
        config=StreamingSubsystemConfig(
            youtube=YouTubeSubsystemConfig(mode=YouTubeAdapterMode.DISABLED),
            obs=ObsSubsystemConfig(mode=ObsAdapterMode.DISABLED),
        ),
        secret_provider=NullSecretProvider(),
    )

    assert {
        name: value for name, value in sys.modules.items() if name.startswith("google")
    } == google_modules
    assert sys.modules.get("obsws_python") is obs_module


def test_real_modes_reject_missing_secrets_without_loading_sdk() -> None:
    config = StreamingSubsystemConfig(
        youtube=YouTubeSubsystemConfig(mode=YouTubeAdapterMode.GOOGLE),
        obs=ObsSubsystemConfig(mode=ObsAdapterMode.OBS_WEBSOCKET),
    )
    with pytest.raises(ValueError, match="required_secret_missing"):
        build_streaming_subsystem(
            config=config,
            secret_provider=StaticSecretProvider({}),
        )
