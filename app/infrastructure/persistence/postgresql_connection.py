"""PostgreSQL の接続上限・取引・安全な失敗分類を所有する。"""

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from importlib import import_module
from types import TracebackType
from typing import Literal, Protocol, cast

from .contracts import PersistenceError, PersistenceFailureCode


class PostgresCursor(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class PostgresConnection(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> PostgresCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PostgresPool(Protocol):
    def getconn(self, timeout: float | None = None) -> PostgresConnection: ...

    def putconn(self, connection: PostgresConnection) -> None: ...

    def close(self, timeout: float = 5.0) -> None: ...


@dataclass(frozen=True, slots=True)
class PostgresConnectionPolicy:
    max_connections: int
    max_waiting: int
    acquire_timeout_seconds: float
    connect_timeout_seconds: int
    statement_timeout_ms: int
    close_timeout_seconds: float
    transaction_timeout_ms: int

    def __post_init__(self) -> None:
        from math import isfinite

        for name in (
            "max_connections",
            "max_waiting",
            "connect_timeout_seconds",
            "statement_timeout_ms",
            "transaction_timeout_ms",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name}は正の整数で指定してください")
        for name in ("acquire_timeout_seconds", "close_timeout_seconds"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name}は有限の正の秒数で指定してください")


@dataclass(frozen=True, slots=True)
class PostgresEndpoint:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    sslmode: str = "verify-full"

    def __post_init__(self) -> None:
        if any(
            not isinstance(v, str) or not v or "\x00" in v
            for v in (self.host, self.database, self.user)
        ):
            raise ValueError("PostgreSQL の接続先が不正です")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("PostgreSQL の接続ポートが不正です")
        if not isinstance(self.password, str) or "\x00" in self.password:
            raise ValueError("PostgreSQL の認証情報が不正です")
        if self.sslmode not in {
            "disable",
            "allow",
            "prefer",
            "require",
            "verify-ca",
            "verify-full",
        }:
            raise ValueError("PostgreSQL の接続暗号化方式が不正です")


def normalize_postgres_error(error: Exception) -> PersistenceError:
    if isinstance(error, PersistenceError):
        return error
    state = getattr(error, "sqlstate", None)
    name = type(error).__name__
    if state in {"40001", "40P01"}:
        code = PersistenceFailureCode.PERSISTENCE_CONFLICT
    elif isinstance(state, str) and state.startswith("23"):
        code = PersistenceFailureCode.CONSTRAINT_VIOLATION
    elif state in {"57014", "55P03", "25P03", "25P04"} or name in {
        "PoolTimeout",
        "ConnectionTimeout",
    }:
        code = PersistenceFailureCode.TIMEOUT
    elif name == "PoolClosed":
        code = PersistenceFailureCode.CLOSED
    elif name == "OperationalError" or (isinstance(state, str) and state.startswith("08")):
        code = PersistenceFailureCode.CONNECTION_FAILED
    elif isinstance(state, str) and state.startswith("42"):
        code = PersistenceFailureCode.MIGRATION_FAILED
    else:
        code = PersistenceFailureCode.UNAVAILABLE
    return PersistenceError(code, "PostgreSQL の保存処理を完了できませんでした")


class PostgresDatabase:
    """上限付き接続群を所有する。同期入口は実行ループの外から使用する。"""

    def __init__(self, pool: PostgresPool, policy: PostgresConnectionPolicy) -> None:
        self._pool = pool
        self.policy = policy
        self._closed = False

    @classmethod
    def connect(
        cls, endpoint: PostgresEndpoint, policy: PostgresConnectionPolicy
    ) -> "PostgresDatabase":
        try:
            pool_type = import_module("psycopg_pool").NullConnectionPool
            # 空の接続を常駐させず、認証情報をログに出す再接続処理を起動しない。
            pool = pool_type(
                kwargs={
                    "host": endpoint.host,
                    "port": endpoint.port,
                    "dbname": endpoint.database,
                    "user": endpoint.user,
                    "password": endpoint.password,
                    "passfile": "/dev/null",
                    "sslmode": endpoint.sslmode,
                    "connect_timeout": policy.connect_timeout_seconds,
                    "options": (
                        "-c default_transaction_isolation=repeatable\\ read "
                        f"-c transaction_timeout={policy.transaction_timeout_ms} "
                        f"-c statement_timeout={policy.statement_timeout_ms}"
                    ),
                },
                max_size=policy.max_connections,
                max_waiting=policy.max_waiting,
                timeout=policy.acquire_timeout_seconds,
                open=True,
            )
        except Exception as error:
            raise normalize_postgres_error(error) from None
        return cls(cast(PostgresPool, pool), policy)

    def transaction(self) -> AbstractContextManager[PostgresConnection]:
        if self._closed:
            raise PersistenceError(PersistenceFailureCode.CLOSED, "PostgreSQL 接続は終了済みです")
        return _Transaction(self._pool, self.policy)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._pool.close(timeout=self.policy.close_timeout_seconds)
        except Exception as error:
            raise normalize_postgres_error(error) from None
        self._closed = True


class _Transaction:
    def __init__(self, pool: PostgresPool, policy: PostgresConnectionPolicy) -> None:
        self._pool = pool
        self._policy = policy
        self._connection: PostgresConnection | None = None

    def __enter__(self) -> PostgresConnection:
        try:
            self._connection = self._pool.getconn(self._policy.acquire_timeout_seconds)
            self._connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._policy.statement_timeout_ms),),
            )
            return self._connection
        except Exception as error:
            if self._connection is not None:
                try:
                    self._connection.rollback()
                except Exception:
                    pass
                try:
                    self._pool.putconn(self._connection)
                except Exception:
                    pass
            raise normalize_postgres_error(error) from None

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        connection = self._connection
        assert connection is not None
        failure: Exception | None = None
        try:
            if kind is None:
                connection.commit()
            else:
                connection.rollback()
        except Exception as caught:
            failure = caught
        try:
            self._pool.putconn(connection)
        except Exception as caught:
            if failure is None:
                failure = caught
        # 期限で接続が切れた後の取消失敗で、元の期限超過を上書きしない。
        if isinstance(error, Exception):
            raise normalize_postgres_error(error) from None
        if failure is not None:
            raise normalize_postgres_error(failure) from None
        return False
