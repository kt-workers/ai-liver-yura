from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_streaming_admin_has_no_legacy_client_or_event_alias() -> None:
    gui = ROOT / "gui" / "yura-streaming-admin"
    assert not (gui / "client" / "core_api_client.py").exists()
    assert not (gui / "client" / "event_stream_client.py").exists()
    source = "\n".join(path.read_text(encoding="utf-8") for path in gui.rglob("*.py"))
    assert "Core" + "ApiClient" not in source
    assert "core" + "-event" not in source


def test_core_config_has_no_legacy_streaming_owner() -> None:
    assert not (ROOT / "config" / "streaming.yaml").exists()
    source = (ROOT / "config" / "index.yaml").read_text(encoding="utf-8")
    assert "streaming.yaml" not in source


def test_migration_roadmap_reports_all_steps_complete() -> None:
    source = (
        ROOT / "docs" / "architecture" / "subsystem_migration_roadmap_v1.0.0.md"
    ).read_text(encoding="utf-8")
    assert "15/15" in source
    assert "残り: 0" in source
