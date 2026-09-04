from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.contracts.common import JsonValue, thaw_json
from app.subsystems.gui_admin import (
    AdminCommandRequest,
    AdminReadModelEnvelope,
    GuiAdminAvailability,
    GuiAdminOperationalPolicy,
    GuiAdminReadModelBroker,
    GuiAdminReadModelKind,
)

NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def model(
    *,
    kind: GuiAdminReadModelKind = GuiAdminReadModelKind.SYSTEM_HEALTH,
    owner: str = "runtime",
    revision: int = 1,
    payload: JsonValue | None = None,
) -> AdminReadModelEnvelope:
    return AdminReadModelEnvelope(
        model_kind=kind,
        schema_version=1,
        source_owner=owner,
        source_revision=revision,
        generated_at=NOW,
        payload={"revision": revision} if payload is None else payload,
    )


def test_operational_policy_matches_canonical_defaults_and_rejects_invalid_values() -> None:
    policy = GuiAdminOperationalPolicy()
    assert policy.max_read_model_payload_bytes == 262144
    assert policy.max_command_payload_bytes == 65536
    assert policy.per_client_update_capacity == 32
    assert policy.max_history_page_items == 200
    assert policy.max_active_subscriptions_per_client == 64
    assert policy.command_timeout_seconds == 30.0
    with pytest.raises(ValueError):
        GuiAdminOperationalPolicy(per_client_update_capacity=0)
    with pytest.raises(ValueError):
        GuiAdminOperationalPolicy(command_timeout_seconds=float("inf"))


def test_read_model_freezes_payload_and_enforces_availability_reason_contract() -> None:
    nested: dict[str, JsonValue] = {"count": 1}
    payload: dict[str, JsonValue] = {"status": "ok", "nested": nested}
    envelope = model(payload=payload)
    payload["status"] = "changed"
    nested["count"] = 99
    assert thaw_json(envelope.payload) == {"status": "ok", "nested": {"count": 1}}

    with pytest.raises(ValueError):
        AdminReadModelEnvelope(
            GuiAdminReadModelKind.SYSTEM_HEALTH,
            1,
            "runtime",
            1,
            NOW,
            {},
            GuiAdminAvailability.DEGRADED,
        )


def test_publish_is_monotonic_and_same_revision_is_idempotent_only_for_same_value() -> None:
    broker = GuiAdminReadModelBroker()
    first = model(revision=1)
    broker.publish(first)
    broker.publish(first)
    second = model(revision=2)
    broker.publish(second)
    assert broker.latest(GuiAdminReadModelKind.SYSTEM_HEALTH, "runtime") == second
    with pytest.raises(ValueError):
        broker.publish(model(revision=1))
    with pytest.raises(ValueError):
        broker.publish(model(revision=2, payload={"different": True}))


def test_payload_limit_rejects_whole_read_model_without_truncation() -> None:
    broker = GuiAdminReadModelBroker(
        GuiAdminOperationalPolicy(max_read_model_payload_bytes=8)
    )
    with pytest.raises(ValueError):
        broker.publish(model(payload={"message": "too long"}))
    assert broker.latest(GuiAdminReadModelKind.SYSTEM_HEALTH, "runtime") is None


def test_subscription_coalesces_same_state_identity_to_latest_revision() -> None:
    broker = GuiAdminReadModelBroker()
    broker.subscribe(
        client_id="client:1",
        subscription_id="sub:1",
        model_kind=GuiAdminReadModelKind.SYSTEM_HEALTH,
        source_owner="runtime",
    )
    broker.publish(model(revision=1))
    broker.publish(model(revision=2))
    batch = broker.poll("client:1")
    assert len(batch.updates) == 1
    assert batch.updates[0].source_revision == 2
    assert batch.resync_required is False


def test_slow_client_capacity_never_blocks_publication_and_requires_authoritative_resync() -> None:
    broker = GuiAdminReadModelBroker(GuiAdminOperationalPolicy(per_client_update_capacity=1))
    broker.subscribe(
        client_id="client:slow",
        subscription_id="sub:health",
        model_kind=GuiAdminReadModelKind.SYSTEM_HEALTH,
        source_owner="runtime",
    )
    broker.subscribe(
        client_id="client:slow",
        subscription_id="sub:body",
        model_kind=GuiAdminReadModelKind.BODY_SUMMARY,
        source_owner="body",
    )
    health = model(revision=1)
    body = model(kind=GuiAdminReadModelKind.BODY_SUMMARY, owner="body", revision=4)
    broker.publish(health)
    broker.publish(body)

    batch = broker.poll("client:slow")
    assert len(batch.updates) == 1
    assert batch.resync_required is True
    assert batch.rejected_update_count == 1
    assert broker.latest(GuiAdminReadModelKind.BODY_SUMMARY, "body") == body
    assert broker.authoritative_snapshot("client:slow") == (body, health)


def test_subscription_limits_duplicates_disconnect_and_reconnect_latest_snapshot() -> None:
    broker = GuiAdminReadModelBroker(
        GuiAdminOperationalPolicy(max_active_subscriptions_per_client=1)
    )
    broker.publish(model(revision=3))
    broker.subscribe(
        client_id="client:1",
        subscription_id="sub:1",
        model_kind=GuiAdminReadModelKind.SYSTEM_HEALTH,
        source_owner="runtime",
    )
    assert broker.poll("client:1").updates[0].source_revision == 3
    with pytest.raises(ValueError):
        broker.subscribe(
            client_id="client:1",
            subscription_id="sub:2",
            model_kind=GuiAdminReadModelKind.BODY_SUMMARY,
            source_owner="body",
        )
    broker.disconnect("client:1")
    broker.publish(model(revision=4))
    broker.subscribe(
        client_id="client:1",
        subscription_id="sub:new",
        model_kind=GuiAdminReadModelKind.SYSTEM_HEALTH,
        source_owner="runtime",
    )
    assert broker.poll("client:1").updates[0].source_revision == 4


def test_admin_command_request_freezes_payload_and_tracks_expected_revision() -> None:
    payload: dict[str, JsonValue] = {"enabled": True}
    request = AdminCommandRequest(
        command_id="command:1",
        command_kind="plugin.disable",
        target_owner="plugin-registry",
        target_ref="plugin:test",
        expected_revision=7,
        payload=payload,
        requested_at=NOW,
        actor_context={"actor": "operator"},
    )
    payload["enabled"] = False
    assert thaw_json(request.payload) == {"enabled": True}
    assert request.expected_revision == 7
    assert request.payload_size_bytes > 0
