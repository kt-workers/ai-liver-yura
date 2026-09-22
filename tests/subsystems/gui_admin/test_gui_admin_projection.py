"""稼働設定の安全な投影と、独立したGUI配置設定を確認する。"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config.gui_admin import load_gui_admin_config
from app.config.minimum_brain import load_minimum_brain_config
from app.runtime.kernel.clock import FakeRuntimeClock
from app.subsystems.gui_admin.configuration_projection import (
    MinimumBrainConfigurationReadModelProjector,
)
from app.subsystems.gui_admin.contracts import GuiAdminOperationalPolicy


def test_projection_uses_injected_generation_and_excludes_private_configuration() -> None:
    config = load_minimum_brain_config(Path("resources/config/v2/minimum_brain.yaml").read_text())
    config = replace(config, config_revision=7, character_definition_path="private-not-for-browser")
    clock = FakeRuntimeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
    projector = MinimumBrainConfigurationReadModelProjector(
        config, clock, GuiAdminOperationalPolicy()
    )
    original = projector.json_bytes
    clock.advance(60)
    assert projector.json_bytes == original
    wire = json.loads(original)
    assert set(wire) == {
        "model_kind",
        "schema_version",
        "source_owner",
        "source_revision",
        "generated_at",
        "availability",
        "degraded_reasons",
        "payload",
    }
    assert wire["source_revision"] == 7
    assert wire["generated_at"] == "2026-09-22T00:00:00Z"
    assert wire["availability"] == "available"
    assert set(wire["payload"]["effective_values"]) == {
        "schema_id",
        "config_id",
        "config_revision",
        "brain_module_registrations",
    }
    assert wire["payload"]["secret_fields"] == []
    assert b"private-not-for-browser" not in original
    assert b"execution_policy" not in original
    with pytest.raises(ValueError, match="容量"):
        MinimumBrainConfigurationReadModelProjector(
            config,
            clock,
            GuiAdminOperationalPolicy(max_read_model_payload_bytes=len(original) - 1),
        )
    assert (
        MinimumBrainConfigurationReadModelProjector(
            config,
            FakeRuntimeClock(datetime(2026, 9, 22, tzinfo=timezone.utc)),
            GuiAdminOperationalPolicy(max_read_model_payload_bytes=len(original)),
        ).json_bytes
        == original
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("bind_host: 127.0.0.1", "bind_host: 0.0.0.0"),
        ("port: 8765", "port: true"),
        ("access_level: public_visualization", "access_level: operator_mutation"),
        ("max_header_count: 64", "max_header_count: true"),
        ("max_request_body_bytes: 0", "max_request_body_bytes: 1"),
        ("shutdown_grace_seconds: 2.0", "shutdown_grace_seconds: .nan"),
        ("port: 8765", "port: 8765\nport: 9876"),
        ("port: 8765", "unapproved_private_value: never-disclose"),
    ],
)
def test_gui_configuration_rejects_unsafe_or_ambiguous_values(old: str, new: str) -> None:
    source = Path("resources/config/v2/gui_admin.yaml").read_text()
    with pytest.raises(ValueError, match="GUIの本番設定を読み込めません") as error:
        load_gui_admin_config(source.replace(old, new))
    assert "never-disclose" not in str(error.value)
    assert error.value.__suppress_context__


def test_gui_configuration_has_explicit_independent_policies() -> None:
    config = load_gui_admin_config(Path("resources/config/v2/gui_admin.yaml").read_text())
    assert config.bind_host == "127.0.0.1"
    assert config.gui_operational_policy.policy_revision == 2
    assert config.gui_http_transport_policy.max_concurrent_requests == 16
    assert config.gui_http_transport_policy.max_header_count == 64
    assert config.gui_http_transport_policy.max_request_body_bytes == 0


def test_read_only_routes_preserve_head_and_safe_failure_contracts() -> None:
    from app.subsystems.gui_admin.http_application import SAFE_HEADERS, GuiHttpApplication

    config = load_minimum_brain_config(Path("resources/config/v2/minimum_brain.yaml").read_text())
    app = GuiHttpApplication(
        MinimumBrainConfigurationReadModelProjector(
            config,
            FakeRuntimeClock(datetime(2026, 9, 22, tzinfo=timezone.utc)),
            GuiAdminOperationalPolicy(),
        )
    )
    for path in (
        b"/",
        b"/assets/app.js",
        b"/assets/app.css",
        b"/api/v1/configuration/minimum-brain",
        b"/healthz",
    ):
        get = app.respond(b"GET", path, has_body=False)
        head = app.respond(b"HEAD", path, has_body=False)
        assert head.status == get.status
        assert head.headers == get.headers
        assert head.body == b""
        assert set(SAFE_HEADERS) <= set(get.headers)
        for method in (b"POST", b"PUT", b"PATCH", b"DELETE"):
            rejected = app.respond(method, path, has_body=False)
            assert rejected.status == 405
            assert ("Allow", "GET, HEAD") in rejected.headers
    for path, has_body, status, code in (
        (b"/missing-private", False, 404, "GUI_ROUTE_NOT_FOUND"),
        (b"/?private-value", False, 400, "GUI_QUERY_NOT_ALLOWED"),
        (b"/", True, 413, "GUI_REQUEST_BODY_NOT_ALLOWED"),
    ):
        result = app.respond(b"GET", path, has_body=has_body)
        assert result.status == status
        assert json.loads(result.body) == {"error": {"code": code}}
        assert b"private" not in result.body
        assert app.respond(b"HEAD", path, has_body=has_body).body == b""
