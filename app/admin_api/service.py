"""Core-only diagnostics and settings application service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone


class CoreAdminService:
    def __init__(
        self,
        *,
        runtime_snapshot: Callable[[], Mapping[str, object]] | None = None,
        settings_snapshot: Callable[[], Mapping[str, object]] | None = None,
        manual_checks: Mapping[str, Callable[[], object]] | None = None,
    ) -> None:
        self._runtime_snapshot = runtime_snapshot or (lambda: {})
        self._settings_snapshot = settings_snapshot or (lambda: {})
        self._manual_checks = dict(manual_checks or {})

    def health(self) -> dict[str, object]:
        return {
            "status": "healthy",
            "service": "core",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def diagnostics(self) -> dict[str, object]:
        return {
            "runtime": dict(self._runtime_snapshot()),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    def settings(self) -> dict[str, object]:
        return {"values": dict(self._settings_snapshot()), "read_only": True}

    def run_manual_check(self, check_id: str) -> dict[str, object]:
        check = self._manual_checks.get(check_id)
        if check is None:
            raise KeyError(check_id)
        return {"check_id": check_id, "result": check()}

    def list_manual_checks(self) -> dict[str, object]:
        return {"items": sorted(self._manual_checks)}
