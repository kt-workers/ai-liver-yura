import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / "gui" / "yura-streaming-admin"
sys.path.insert(0, str(ROOT))

from config import StreamingSubsystemAdminConfig  # noqa: E402


def test_new_environment_names_win_over_legacy_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_LIVER_ADMIN_API_URL", "http://legacy:8765")
    monkeypatch.setenv("STREAMING_SUBSYSTEM_ADMIN_API_URL", "http://subsystem:8781/")
    monkeypatch.setenv("STREAMING_SUBSYSTEM_ADMIN_API_TIMEOUT", "3")
    config = StreamingSubsystemAdminConfig.from_environment()
    assert config.base_url == "http://subsystem:8781"
    assert config.timeout_seconds == 3


def test_legacy_environment_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STREAMING_SUBSYSTEM_ADMIN_API_URL", raising=False)
    monkeypatch.setenv("AI_LIVER_ADMIN_API_URL", "http://legacy:8765/")
    assert StreamingSubsystemAdminConfig.from_environment().base_url == "http://127.0.0.1:8781"


def test_default_uses_subsystem_port_and_token_is_hidden() -> None:
    config = StreamingSubsystemAdminConfig(token="not-for-repr")
    assert config.base_url == "http://127.0.0.1:8781"
    assert "not-for-repr" not in repr(config)
    with pytest.raises(ValueError, match="positive"):
        StreamingSubsystemAdminConfig(timeout_seconds=0)
