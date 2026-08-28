from __future__ import annotations

from tools.loop_engine.operational_store import PostgreSQLOperationalStore, StoreStatus


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.calls.append((query, parameters))


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_value = FakeCursor()
        self.committed = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_value

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.committed = False

    def close(self) -> None:
        self.closed = True


def test_records_bounded_secret_safe_operational_evidence() -> None:
    connection = FakeConnection()
    result = PostgreSQLOperationalStore(lambda: connection).record(
        "review_jobs", "attempt-1", {"status": "IN_FLIGHT", "model": "gpt-5.6-terra"}
    )

    assert result.status is StoreStatus.STORED
    assert connection.committed and connection.closed
    query, _ = connection.cursor_value.calls[0]
    assert "ON CONFLICT (identity) DO NOTHING" in query


def test_refuses_secret_payloads_without_connecting() -> None:
    result = PostgreSQLOperationalStore(lambda: (_ for _ in ()).throw(AssertionError())).record(
        "review_results", "attempt-1", {"raw_response": "forbidden"}
    )
    assert result.status is StoreStatus.INVALID


def test_database_outage_is_typed_degraded_path() -> None:
    result = PostgreSQLOperationalStore(lambda: (_ for _ in ()).throw(OSError())).record(
        "loop_events", "event-1", {"transition": "OBSERVE"}
    )
    assert result.status is StoreStatus.DB_UNAVAILABLE
