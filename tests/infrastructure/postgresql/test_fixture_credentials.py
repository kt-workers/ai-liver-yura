"""隔離PostgreSQL fixtureの認証情報境界を検証する。"""

import traceback
from collections.abc import Callable, Generator
from pathlib import Path
from typing import NoReturn, cast

import pytest

from app.infrastructure.persistence.postgresql_connection import PostgresEndpoint
from tests.infrastructure.postgresql import conftest

_SENTINELS = (
    "fixture-secret-sentinel",
    "fixture-host-sentinel",
    "fixture-user-sentinel",
    "fixture-port-sentinel",
    "fixture-dsn-sentinel",
    "raw-driver-diagnostic-sentinel",
)


def _raise_raw_driver_failure() -> NoReturn:
    raise RuntimeError(" ".join(_SENTINELS))


def _assert_sanitized_failure(
    diagnostic: str, operation: Callable[[], object]
) -> None:
    with pytest.raises(conftest.IsolatedPostgresFixtureFailure) as caught:
        conftest._run_fixture_operation(operation, diagnostic)
    error = caught.value
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert str(error) == diagnostic
    assert error.__cause__ is None
    assert error.__context__ is None
    for sentinel in _SENTINELS:
        assert sentinel not in str(error)
        assert sentinel not in repr(error)
        assert sentinel not in rendered


def _assert_sentinel_absent_from_exception_chain(error: BaseException) -> None:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        for sentinel in _SENTINELS:
            assert sentinel not in str(current)
            assert sentinel not in repr(current)
        current = current.__cause__ or current.__context__


class _FailingAdmin:
    def execute(self, _: object) -> None:
        _raise_raw_driver_failure()


class _FakeSqlExpression:
    def format(self, _: object) -> "_FakeSqlExpression":
        return self


class _FakeSql:
    def SQL(self, _: str) -> _FakeSqlExpression:
        return _FakeSqlExpression()

    def Identifier(self, _: str) -> object:
        return object()


class _FakePsycopg:
    sql = _FakeSql()

    def __init__(self, admin: object | None = None) -> None:
        self._admin = admin

    def connect(self, **_: object) -> object:
        if self._admin is None:
            _raise_raw_driver_failure()
        return self._admin


class _FakeAdmin:
    def __init__(self, *, fail_execute_at: int | None = None) -> None:
        self._fail_execute_at = fail_execute_at
        self.execute_count = 0
        self.closed = False

    def execute(self, _: object) -> None:
        self.execute_count += 1
        if self.execute_count == self._fail_execute_at:
            _raise_raw_driver_failure()

    def close(self) -> None:
        self.closed = True


def _set_fixture_environment(monkeypatch: pytest.MonkeyPatch, *, port: str = "5432") -> None:
    monkeypatch.setenv("YURA_TEST_POSTGRES_HOST", "fixture-host-sentinel")
    monkeypatch.setenv("YURA_TEST_POSTGRES_PORT", port)
    monkeypatch.setenv("YURA_TEST_POSTGRES_USER", "fixture-user-sentinel")
    monkeypatch.setenv("YURA_TEST_POSTGRES_PASSWORD", "fixture-secret-sentinel")
    monkeypatch.delenv("YURA_TEST_POSTGRES_SOCKET", raising=False)


def _assert_public_fixture_failure(
    diagnostic: str, generator: Generator[PostgresEndpoint, None, None]
) -> None:
    with pytest.raises(pytest.fail.Exception) as caught:
        next(generator)
    error = caught.value
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert str(error) == diagnostic
    assert error.__cause__ is None
    _assert_sentinel_absent_from_exception_chain(error)
    for sentinel in _SENTINELS:
        assert sentinel not in rendered


def _endpoint_generator() -> Generator[PostgresEndpoint, None, None]:
    wrapped = conftest.endpoint.__wrapped__  # type: ignore[attr-defined]
    return cast(Generator[PostgresEndpoint, None, None], wrapped())


def test_unspecified_password_keeps_ci_isolated_credential() -> None:
    password = conftest.resolve_test_password({})
    assert password == "isolated-test-no-auth"


def test_explicit_password_is_used_without_dotenv_loading() -> None:
    password = conftest.resolve_test_password(
        {"YURA_TEST_POSTGRES_PASSWORD": "fixture-only-credential"}
    )
    endpoint = PostgresEndpoint("test-host", 5432, "yura_test_fixture", "test-user", password)
    assert "password=" not in repr(endpoint)
    source = Path(conftest.__file__).read_text(encoding="utf-8")
    assert "load_dotenv" not in source
    assert "open(" not in source
    assert "Path(" not in source


def test_empty_explicit_password_fails_without_echoing_it() -> None:
    with pytest.raises(ValueError) as caught:
        conftest.resolve_test_password({"YURA_TEST_POSTGRES_PASSWORD": ""})
    assert str(caught.value) == "YURA_TEST_POSTGRES_PASSWORDは空にできません"


def test_reduced_subprocess_environment_inherits_only_explicit_password() -> None:
    child = conftest.subprocess_test_environment(
        {
            "YURA_TEST_POSTGRES_PASSWORD": "fixture-only-credential",
            "UNRELATED_CREDENTIAL": "must-not-propagate",
        },
        path="/usr/bin",
        pythonpath="test-path",
    )
    assert child == {
        "PATH": "/usr/bin",
        "PYTHONPATH": "test-path",
        "YURA_TEST_POSTGRES_PASSWORD": "fixture-only-credential",
    }


def test_reduced_subprocess_environment_keeps_ci_fallback_unset() -> None:
    child = conftest.subprocess_test_environment({}, path="/usr/bin", pythonpath="test-path")
    assert child == {"PATH": "/usr/bin", "PYTHONPATH": "test-path"}


def test_temporary_database_name_is_never_a_production_database_name() -> None:
    first = conftest.temporary_database_name()
    second = conftest.temporary_database_name()
    assert first.startswith("yura_test_")
    assert second.startswith("yura_test_")
    assert first != second


def test_admin_connection_failure_hides_raw_driver_diagnostic() -> None:
    _assert_sanitized_failure(
        "隔離PostgreSQLへ接続できません", _raise_raw_driver_failure
    )


def test_fixture_admin_connection_failure_hides_raw_driver_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fixture_environment(monkeypatch)
    monkeypatch.setattr(conftest, "import_module", lambda _: _FakePsycopg())
    generator = _endpoint_generator()
    _assert_public_fixture_failure("隔離PostgreSQLへ接続できません", generator)


def test_fixture_port_failure_hides_raw_port_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fixture_environment(monkeypatch, port="fixture-port-sentinel")
    generator = _endpoint_generator()
    _assert_public_fixture_failure("隔離PostgreSQL接続設定が不正です", generator)


def test_database_create_failure_hides_raw_driver_diagnostic() -> None:
    admin = _FailingAdmin()
    _assert_sanitized_failure(
        "隔離PostgreSQL試験DBを準備できません", lambda: admin.execute("CREATE DATABASE")
    )


def test_fixture_database_create_failure_hides_raw_driver_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fixture_environment(monkeypatch)
    admin = _FakeAdmin(fail_execute_at=1)
    monkeypatch.setattr(conftest, "import_module", lambda _: _FakePsycopg(admin))
    generator = _endpoint_generator()
    _assert_public_fixture_failure("隔離PostgreSQL試験DBを準備できません", generator)
    assert admin.closed


def test_database_drop_failure_hides_raw_driver_diagnostic() -> None:
    admin = _FailingAdmin()
    _assert_sanitized_failure(
        "隔離PostgreSQL試験DBを回収できません", lambda: admin.execute("DROP DATABASE")
    )


def test_fixture_database_drop_failure_hides_raw_driver_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fixture_environment(monkeypatch)
    admin = _FakeAdmin(fail_execute_at=2)
    monkeypatch.setattr(conftest, "import_module", lambda _: _FakePsycopg(admin))
    generator = _endpoint_generator()
    next(generator)
    with pytest.raises(pytest.fail.Exception) as caught:
        generator.close()
    error = caught.value
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert str(error) == "隔離PostgreSQL試験DBを回収できません"
    assert error.__cause__ is None
    for sentinel in _SENTINELS:
        assert sentinel not in str(error)
        assert sentinel not in repr(error)
        assert sentinel not in rendered
    assert admin.closed


def test_test_body_failure_is_not_a_fixture_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fixture_environment(monkeypatch)
    admin = _FakeAdmin()
    monkeypatch.setattr(conftest, "import_module", lambda _: _FakePsycopg(admin))
    generator = _endpoint_generator()
    next(generator)
    with pytest.raises(AssertionError, match="test-body-sentinel"):
        generator.throw(AssertionError("test-body-sentinel"))
    assert admin.execute_count == 2
    assert admin.closed
