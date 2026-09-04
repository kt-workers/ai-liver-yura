from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Protocol

from app.domain.contracts.common import require_identifier

from .contracts import (
    AdminCommandRequest,
    AdminCommandResult,
    AdminCommandStatus,
    GuiAdminOperationalPolicy,
)


class AdminCommandOwnerPort(Protocol):
    @property
    def owner_id(self) -> str: ...

    def current_revision(self) -> int: ...

    async def execute_admin_command(self, request: AdminCommandRequest) -> AdminCommandResult: ...


class GuiAdminCommandDispatcher:
    def __init__(
        self,
        owners: Mapping[str, AdminCommandOwnerPort],
        policy: GuiAdminOperationalPolicy | None = None,
    ) -> None:
        self._policy = policy or GuiAdminOperationalPolicy()
        normalized: dict[str, AdminCommandOwnerPort] = {}
        for owner_id, owner in owners.items():
            require_identifier(owner_id, "owner_id")
            if owner.owner_id != owner_id:
                raise ValueError("owner registry keyとowner_idが一致しません")
            if owner_id in normalized:
                raise ValueError("owner_idは一意でなければなりません")
            normalized[owner_id] = owner
        self._owners = normalized
        self._terminal_command_ids: set[str] = set()
        self._in_flight_command_ids: set[str] = set()

    @property
    def policy(self) -> GuiAdminOperationalPolicy:
        return self._policy

    async def execute(self, request: AdminCommandRequest) -> AdminCommandResult:
        if not isinstance(request, AdminCommandRequest):
            raise ValueError("request が不正です")
        if request.payload_size_bytes > self._policy.max_command_payload_bytes:
            return self._terminal_failure(
                request.command_id,
                AdminCommandStatus.REJECTED,
                "COMMAND_PAYLOAD_LIMIT_EXCEEDED",
                "Admin Command payloadが運用上限を超えています",
            )
        if request.command_id in self._terminal_command_ids:
            return self._duplicate(request.command_id)
        if request.command_id in self._in_flight_command_ids:
            return AdminCommandResult(
                command_id=request.command_id,
                status=AdminCommandStatus.DUPLICATE,
                failure_code="COMMAND_ALREADY_IN_FLIGHT",
                sanitized_message="同じAdmin Commandが実行中です",
            )

        owner = self._owners.get(request.target_owner)
        if owner is None:
            return self._terminal_failure(
                request.command_id,
                AdminCommandStatus.UNAVAILABLE,
                "ADMIN_OWNER_UNAVAILABLE",
                "対象ownerのAdmin Command境界を利用できません",
            )

        try:
            revision_before = owner.current_revision()
            self._require_revision_value(revision_before)
        except Exception:
            return self._terminal_failure(
                request.command_id,
                AdminCommandStatus.UNAVAILABLE,
                "ADMIN_OWNER_REVISION_UNAVAILABLE",
                "対象ownerのrevisionを取得できません",
            )

        if request.expected_revision is not None and request.expected_revision != revision_before:
            return self._terminal_failure(
                request.command_id,
                AdminCommandStatus.STALE_ADMIN_VIEW,
                "STALE_ADMIN_VIEW",
                "画面のrevisionが最新状態と一致しません",
                owner_revision_before=revision_before,
                owner_revision_after=revision_before,
            )

        self._in_flight_command_ids.add(request.command_id)
        try:
            try:
                result = await asyncio.wait_for(
                    owner.execute_admin_command(request),
                    timeout=self._policy.command_timeout_seconds,
                )
            except asyncio.TimeoutError:
                revision_after = self._safe_revision(owner, revision_before)
                return self._terminal_failure(
                    request.command_id,
                    AdminCommandStatus.TIMED_OUT,
                    "ADMIN_COMMAND_TIMED_OUT",
                    "Admin Commandの結果確認がtimeoutしました",
                    owner_revision_before=revision_before,
                    owner_revision_after=revision_after,
                )
            except Exception:
                revision_after = self._safe_revision(owner, revision_before)
                return self._terminal_failure(
                    request.command_id,
                    AdminCommandStatus.FAILED,
                    "ADMIN_OWNER_EXECUTION_FAILED",
                    "Admin Commandの実行に失敗しました",
                    owner_revision_before=revision_before,
                    owner_revision_after=revision_after,
                )

            if not isinstance(result, AdminCommandResult) or result.command_id != request.command_id:
                revision_after = self._safe_revision(owner, revision_before)
                return self._terminal_failure(
                    request.command_id,
                    AdminCommandStatus.FAILED,
                    "ADMIN_OWNER_CONTRACT_VIOLATION",
                    "対象ownerから不正なAdmin Command結果が返されました",
                    owner_revision_before=revision_before,
                    owner_revision_after=revision_after,
                )
            self._terminal_command_ids.add(request.command_id)
            return result
        finally:
            self._in_flight_command_ids.discard(request.command_id)

    def _duplicate(self, command_id: str) -> AdminCommandResult:
        return AdminCommandResult(
            command_id=command_id,
            status=AdminCommandStatus.DUPLICATE,
            failure_code="DUPLICATE_ADMIN_COMMAND",
            sanitized_message="同じAdmin Commandは再実行しません",
        )

    def _terminal_failure(
        self,
        command_id: str,
        status: AdminCommandStatus,
        failure_code: str,
        sanitized_message: str,
        *,
        owner_revision_before: int | None = None,
        owner_revision_after: int | None = None,
    ) -> AdminCommandResult:
        self._terminal_command_ids.add(command_id)
        return AdminCommandResult(
            command_id=command_id,
            status=status,
            owner_revision_before=owner_revision_before,
            owner_revision_after=owner_revision_after,
            failure_code=failure_code,
            sanitized_message=sanitized_message,
        )

    @staticmethod
    def _require_revision_value(value: object) -> None:
        if type(value) is not int or value < 0:
            raise ValueError("owner revisionが不正です")

    def _safe_revision(self, owner: AdminCommandOwnerPort, fallback: int) -> int:
        try:
            revision = owner.current_revision()
            self._require_revision_value(revision)
            return revision
        except Exception:
            return fallback


__all__ = ["AdminCommandOwnerPort", "GuiAdminCommandDispatcher"]
