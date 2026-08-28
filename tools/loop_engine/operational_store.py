"""Secret-safe PostgreSQL operational memory for Loop Engineering.

GitHub remains current-state authority.  This adapter records only bounded
execution evidence and exposes a typed degraded result when PostgreSQL is down.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class StoreStatus(str, Enum):
    STORED = "STORED"
    DUPLICATE = "DUPLICATE"
    DB_UNAVAILABLE = "DB_UNAVAILABLE"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class StoreResult:
    status: StoreStatus
    identity: str


class Cursor(Protocol):
    def execute(self, query: str, parameters: tuple[object, ...]) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[], Connection]


class PostgreSQLOperationalStore:
    """One-transaction, unique-identity writes with no secret payload storage."""

    _TABLES = frozenset({"review_jobs", "review_results", "api_usage", "loop_events"})
    _FORBIDDEN = frozenset(
        {
            "authorization",
            "credential",
            "token",
            "prompt",
            "diff",
            "request_body",
            "raw_response",
            "raw_error",
        }
    )

    def __init__(self, connect: ConnectionFactory) -> None:
        self._connect = connect

    def record(self, table: str, identity: str, metadata: Mapping[str, object]) -> StoreResult:
        if table not in self._TABLES or not identity or not self._is_safe(metadata):
            return StoreResult(StoreStatus.INVALID, identity)
        try:
            connection = self._connect()
        except OSError:
            return StoreResult(StoreStatus.DB_UNAVAILABLE, identity)
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"INSERT INTO {table} (identity, metadata) VALUES (%s, %s) "
                "ON CONFLICT (identity) DO NOTHING",
                (identity, json.dumps(dict(metadata), sort_keys=True)),
            )
            connection.commit()
        except OSError:
            connection.rollback()
            return StoreResult(StoreStatus.DB_UNAVAILABLE, identity)
        finally:
            connection.close()
        return StoreResult(StoreStatus.STORED, identity)

    @classmethod
    def _is_safe(cls, metadata: Mapping[str, object]) -> bool:
        def visit(value: object) -> bool:
            if isinstance(value, Mapping):
                return all(
                    isinstance(key, str)
                    and key.lower() not in cls._FORBIDDEN
                    and visit(item)
                    for key, item in value.items()
                )
            return not isinstance(value, (bytes, bytearray))

        return visit(metadata)
