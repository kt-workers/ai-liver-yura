from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.domain.contracts.common import JsonValue
from app.subsystems.gui_admin import (
    AdminCommandRequest,
    AdminCommandResult,
    AdminCommandStatus,
    GuiAdminCommandDispatcher,
    GuiAdminOperationalPolicy,
)

NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def request(
    *,
    command_id: str = "command:1",
    owner: str = "owner:config",
    expected_revision: int | None = 3,
    payload: JsonValue = None,
) -> AdminCommandRequest:
    return AdminCommandRequest(
        command_id=command_id,
        command_kind="replace_configuration",
        target_owner=owner,
        target_ref=None,
        expected_revision=expected_revision,
        payload={} if payload is None else payload,
        requested_at=NOW,
        actor_context={"actor": "operator"},
    )


class Owner:
    owner_id = "owner:config"

    def __init__(self) -> None:
        self.revision = 3
        self.calls: list[AdminCommandRequest] = []
        self.raise_error = False
        self.delay = False

    def current_revision(self) -> int:
        return self.revision

    async def execute_admin_command(self, value: AdminCommandRequest) -> AdminCommandResult:
        self.calls.append(value)
        if self.delay:
            await asyncio.sleep(3600)
        if self.raise_error:
            raise RuntimeError("SECRET=abc123")
        before = self.revision
        self.revision += 1
        return AdminCommandResult(
            command_id=value.command_id,
            status=AdminCommandStatus.APPLIED,
            owner_revision_before=before,
            owner_revision_after=self.revision,
            applied_at=NOW,
        )


def test_typed_owner_handler_applies_and_reports_owner_revision() -> None:
    async def scenario() -> None:
        owner = Owner()
        result = await GuiAdminCommandDispatcher({owner.owner_id: owner}).execute(request())
        assert result.status is AdminCommandStatus.APPLIED
        assert result.owner_revision_before == 3
        assert result.owner_revision_after == 4
        assert len(owner.calls) == 1

    asyncio.run(scenario())


def test_stale_revision_rejected_before_owner_execution() -> None:
    async def scenario() -> None:
        owner = Owner()
        result = await GuiAdminCommandDispatcher({owner.owner_id: owner}).execute(
            request(expected_revision=2)
        )
        assert result.status is AdminCommandStatus.STALE_ADMIN_VIEW
        assert result.failure_code == "STALE_ADMIN_VIEW"
        assert owner.calls == []

    asyncio.run(scenario())


def test_duplicate_command_id_is_not_reexecuted() -> None:
    async def scenario() -> None:
        owner = Owner()
        dispatcher = GuiAdminCommandDispatcher({owner.owner_id: owner})
        first = await dispatcher.execute(request())
        second = await dispatcher.execute(request())
        assert first.status is AdminCommandStatus.APPLIED
        assert second.status is AdminCommandStatus.DUPLICATE
        assert len(owner.calls) == 1

    asyncio.run(scenario())


def test_payload_limit_rejected_before_owner_execution() -> None:
    async def scenario() -> None:
        owner = Owner()
        policy = GuiAdminOperationalPolicy(max_command_payload_bytes=8)
        result = await GuiAdminCommandDispatcher({owner.owner_id: owner}, policy).execute(
            request(payload={"value": "0123456789"})
        )
        assert result.status is AdminCommandStatus.REJECTED
        assert result.failure_code == "COMMAND_PAYLOAD_LIMIT_EXCEEDED"
        assert owner.calls == []

    asyncio.run(scenario())


def test_missing_owner_is_typed_unavailable() -> None:
    async def scenario() -> None:
        result = await GuiAdminCommandDispatcher({}).execute(request(owner="owner:missing"))
        assert result.status is AdminCommandStatus.UNAVAILABLE
        assert result.failure_code == "ADMIN_OWNER_UNAVAILABLE"

    asyncio.run(scenario())


def test_owner_exception_is_sanitized() -> None:
    async def scenario() -> None:
        owner = Owner()
        owner.raise_error = True
        result = await GuiAdminCommandDispatcher({owner.owner_id: owner}).execute(request())
        assert result.status is AdminCommandStatus.FAILED
        assert result.failure_code == "ADMIN_OWNER_EXECUTION_FAILED"
        assert "SECRET" not in (result.sanitized_message or "")
        assert "abc123" not in (result.sanitized_message or "")

    asyncio.run(scenario())


def test_timeout_does_not_claim_applied_fact() -> None:
    async def scenario() -> None:
        owner = Owner()
        owner.delay = True
        policy = GuiAdminOperationalPolicy(command_timeout_seconds=0.001)
        result = await GuiAdminCommandDispatcher({owner.owner_id: owner}, policy).execute(request())
        assert result.status is AdminCommandStatus.TIMED_OUT
        assert result.applied_at is None
        assert result.failure_code == "ADMIN_COMMAND_TIMED_OUT"

    asyncio.run(scenario())


def test_result_contract_rejects_applied_without_applied_at() -> None:
    try:
        AdminCommandResult(
            command_id="command:bad",
            status=AdminCommandStatus.APPLIED,
            owner_revision_before=1,
            owner_revision_after=2,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("APPLIED without applied_at must fail")
