from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from typing import cast

import pytest

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
        result = await GuiAdminCommandDispatcher(
            {owner.owner_id: owner}, GuiAdminOperationalPolicy()
        ).execute(request())
        assert result.status is AdminCommandStatus.APPLIED
        assert result.owner_revision_before == 3
        assert result.owner_revision_after == 4
        assert len(owner.calls) == 1

    asyncio.run(scenario())


def test_stale_revision_rejected_before_owner_execution() -> None:
    async def scenario() -> None:
        owner = Owner()
        result = await GuiAdminCommandDispatcher(
            {owner.owner_id: owner}, GuiAdminOperationalPolicy()
        ).execute(request(expected_revision=2))
        assert result.status is AdminCommandStatus.STALE_ADMIN_VIEW
        assert result.failure_code == "STALE_ADMIN_VIEW"
        assert owner.calls == []

    asyncio.run(scenario())


class IdempotentOwner(Owner):
    def __init__(self) -> None:
        super().__init__()
        self.received: list[AdminCommandRequest] = []

    async def execute_admin_command(self, value: AdminCommandRequest) -> AdminCommandResult:
        self.received.append(value)
        if any(previous.command_id == value.command_id for previous in self.calls):
            return AdminCommandResult(
                command_id=value.command_id,
                status=AdminCommandStatus.DUPLICATE,
                failure_code="OWNER_ALREADY_APPLIED",
            )
        return await super().execute_admin_command(value)


def test_owner_prevents_duplicate_mutation_after_terminal_resubmission() -> None:
    async def scenario() -> None:
        owner = IdempotentOwner()
        dispatcher = GuiAdminCommandDispatcher({owner.owner_id: owner}, GuiAdminOperationalPolicy())
        value = request(expected_revision=None)
        first = await dispatcher.execute(value)
        second = await dispatcher.execute(value)
        assert first.status is AdminCommandStatus.APPLIED
        assert second.status is AdminCommandStatus.DUPLICATE
        assert second.failure_code == "OWNER_ALREADY_APPLIED"
        assert owner.received == [value, value]
        assert len(owner.calls) == 1
        assert owner.revision == 4

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
        result = await GuiAdminCommandDispatcher({}, GuiAdminOperationalPolicy()).execute(
            request(owner="owner:missing")
        )
        assert result.status is AdminCommandStatus.UNAVAILABLE
        assert result.failure_code == "ADMIN_OWNER_UNAVAILABLE"

    asyncio.run(scenario())


def test_owner_exception_is_sanitized() -> None:
    async def scenario() -> None:
        owner = Owner()
        owner.raise_error = True
        result = await GuiAdminCommandDispatcher(
            {owner.owner_id: owner}, GuiAdminOperationalPolicy()
        ).execute(request())
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
        raise AssertionError("APPLIEDには適用時刻が必要です")


def test_dispatcher_requires_and_preserves_policy_snapshot() -> None:
    parameter = inspect.signature(GuiAdminCommandDispatcher).parameters["policy"]
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(ValueError):
        GuiAdminCommandDispatcher({}, cast(GuiAdminOperationalPolicy, None))
    policy = GuiAdminOperationalPolicy()
    dispatcher = GuiAdminCommandDispatcher({}, policy)
    assert dispatcher.policy is policy
    assert dispatcher.policy.policy_id == "v2.gui-admin.default"
    assert dispatcher.policy.policy_revision == 2


class BlockingOwner(Owner):
    def __init__(self, owner_id: str) -> None:
        super().__init__()
        self.owner_id = owner_id
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.revision_reads = 0

    def current_revision(self) -> int:
        self.revision_reads += 1
        return super().current_revision()

    async def execute_admin_command(self, value: AdminCommandRequest) -> AdminCommandResult:
        self.calls.append(value)
        self.entered.set()
        try:
            await self.release.wait()
            return AdminCommandResult(
                command_id=value.command_id,
                status=AdminCommandStatus.APPLIED,
                applied_at=NOW,
            )
        finally:
            self.finished.set()


def test_global_capacity_duplicate_precedence_and_slot_reuse() -> None:
    async def scenario() -> None:
        owners = [BlockingOwner(f"owner:{index}") for index in range(16)]
        policy = GuiAdminOperationalPolicy()
        dispatcher = GuiAdminCommandDispatcher(
            {owner.owner_id: owner for owner in owners},
            policy,
        )
        values = [
            request(command_id=f"command:{index}", owner=owner.owner_id)
            for index, owner in enumerate(owners)
        ]
        tasks = [asyncio.create_task(dispatcher.execute(value)) for value in values]
        try:
            await asyncio.wait_for(
                asyncio.gather(*(owner.entered.wait() for owner in owners)),
                timeout=2,
            )
            assert all(len(owner.calls) == 1 for owner in owners)
            assert all(not task.done() for task in tasks)
            duplicate = await dispatcher.execute(values[0])
            assert duplicate.status is AdminCommandStatus.DUPLICATE
            assert duplicate.failure_code == "COMMAND_ALREADY_IN_FLIGHT"
            overflow_value = request(command_id="command:overflow", owner=owners[0].owner_id)
            overflow = await dispatcher.execute(overflow_value)
            assert overflow.status is AdminCommandStatus.REJECTED
            assert overflow.failure_code == "ADMIN_COMMAND_CONCURRENCY_LIMIT_REACHED"
            assert overflow.applied_at is None
            # 容量判定を所有者の解決・版取得より前に行い、拒否を待機させない。
            missing = await dispatcher.execute(
                request(command_id="command:missing", owner="absent")
            )
            assert missing.failure_code == "ADMIN_COMMAND_CONCURRENCY_LIMIT_REACHED"
            invalid_payload = await dispatcher.execute(
                request(command_id=values[0].command_id, payload="x" * 65537)
            )
            assert invalid_payload.failure_code == "COMMAND_PAYLOAD_LIMIT_EXCEEDED"
            assert all(owner.revision_reads == 1 and len(owner.calls) == 1 for owner in owners)
        finally:
            for owner in owners:
                owner.release.set()
            results = await asyncio.gather(*tasks)
        assert all(result.status is AdminCommandStatus.APPLIED for result in results)
        assert all(len(owner.calls) == 1 for owner in owners)
        # 容量超過で拒否されたIDも再送でき、黙って実行待ちに入っていない。
        accepted = await dispatcher.execute(overflow_value)
        assert accepted.status is AdminCommandStatus.APPLIED
        assert len(owners[0].calls) == 2
        assert all(len(owner.calls) == 1 for owner in owners[1:])
        assert dispatcher.policy is policy

    asyncio.run(scenario())


class RecoverableOwner(Owner):
    def __init__(self, failure: str) -> None:
        super().__init__()
        self.failure = failure

    def current_revision(self) -> int:
        if self.failure == "revision":
            raise RuntimeError("試験用の版取得失敗")
        return super().current_revision()

    async def execute_admin_command(self, value: AdminCommandRequest) -> AdminCommandResult:
        if self.failure == "contract":
            return AdminCommandResult(
                command_id="command:wrong",
                status=AdminCommandStatus.APPLIED,
                applied_at=NOW,
            )
        return await super().execute_admin_command(value)


@pytest.mark.parametrize(
    "failure,status",
    [
        ("revision", AdminCommandStatus.UNAVAILABLE),
        ("stale", AdminCommandStatus.STALE_ADMIN_VIEW),
        ("exception", AdminCommandStatus.FAILED),
        ("contract", AdminCommandStatus.FAILED),
        ("timeout", AdminCommandStatus.TIMED_OUT),
        ("success", AdminCommandStatus.APPLIED),
    ],
)
def test_terminal_paths_release_identity_and_capacity(
    failure: str,
    status: AdminCommandStatus,
) -> None:
    async def scenario() -> None:
        owner = RecoverableOwner(failure)
        owner.raise_error = failure == "exception"
        owner.delay = failure == "timeout"
        owner.revision = 4 if failure == "stale" else 3
        dispatcher = GuiAdminCommandDispatcher(
            {owner.owner_id: owner},
            GuiAdminOperationalPolicy(max_in_flight_commands=1, command_timeout_seconds=0.01),
        )
        first = await dispatcher.execute(request())
        assert first.status is status
        owner.failure = "none"
        owner.raise_error = False
        owner.delay = False
        # 成功後の再送でも現在の版確認を省略しない。
        if failure == "success":
            stale = await dispatcher.execute(request())
            assert stale.status is AdminCommandStatus.STALE_ADMIN_VIEW
        retry = await dispatcher.execute(request(expected_revision=owner.revision))
        assert retry.status is AdminCommandStatus.APPLIED
        assert retry.owner_revision_after == owner.revision

    asyncio.run(scenario())


def test_missing_owner_does_not_permanently_reject_identity() -> None:
    async def scenario() -> None:
        owner = Owner()
        dispatcher = GuiAdminCommandDispatcher(
            {owner.owner_id: owner},
            GuiAdminOperationalPolicy(max_in_flight_commands=1),
        )
        for _ in range(2):
            unavailable = await dispatcher.execute(request(owner="absent"))
            assert unavailable.status is AdminCommandStatus.UNAVAILABLE
            assert unavailable.failure_code == "ADMIN_OWNER_UNAVAILABLE"
        result = await dispatcher.execute(request())
        assert result.status is AdminCommandStatus.APPLIED
        assert len(owner.calls) == 1

    asyncio.run(scenario())


def test_caller_cancellation_reaps_owner_and_releases_slot() -> None:
    async def scenario() -> None:
        owner = BlockingOwner("owner:config")
        dispatcher = GuiAdminCommandDispatcher(
            {owner.owner_id: owner},
            GuiAdminOperationalPolicy(max_in_flight_commands=1),
        )
        task = asyncio.create_task(dispatcher.execute(request()))
        try:
            await asyncio.wait_for(owner.entered.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert owner.finished.is_set()
            owner.release.set()
            assert (await dispatcher.execute(request())).status is AdminCommandStatus.APPLIED
            assert len(owner.calls) == 2
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_timeout_preserves_possible_applied_effect_and_owner_readback() -> None:
    class AppliedThenWaitingOwner(Owner):
        async def execute_admin_command(self, value: AdminCommandRequest) -> AdminCommandResult:
            await super().execute_admin_command(value)
            await asyncio.Event().wait()
            raise AssertionError("試験用の待機が解除されてはいけません")

    async def scenario() -> None:
        owner = AppliedThenWaitingOwner()
        dispatcher = GuiAdminCommandDispatcher(
            {owner.owner_id: owner},
            GuiAdminOperationalPolicy(command_timeout_seconds=0.01),
        )
        result = await dispatcher.execute(request())
        assert result.status is AdminCommandStatus.TIMED_OUT
        assert result.failure_code == "ADMIN_COMMAND_TIMED_OUT"
        assert result.applied_at is None
        assert result.owner_revision_before == 3
        assert result.owner_revision_after == owner.current_revision() == 4
        assert len(owner.calls) == 1

    asyncio.run(scenario())
