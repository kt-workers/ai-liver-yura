"""各試験が専用の空DBを所有し、終了時に回収する。"""

import getpass
import os
from collections.abc import Callable, Iterator, Mapping
from importlib import import_module
from typing import Any, TypeVar
from uuid import uuid4

import pytest

from app.infrastructure.persistence.postgresql_connection import PostgresEndpoint

_TEST_PASSWORD_ENV = "YURA_TEST_POSTGRES_PASSWORD"
_CI_ISOLATED_PASSWORD = "isolated-test-no-auth"
_ADMIN_CONNECTION_FAILURE = "隔離PostgreSQLへ接続できません"
_DATABASE_PREPARATION_FAILURE = "隔離PostgreSQL試験DBを準備できません"
_DATABASE_CLEANUP_FAILURE = "隔離PostgreSQL試験DBを回収できません"
_CONNECTION_CLEANUP_FAILURE = "隔離PostgreSQL接続を回収できません"
_CONNECTION_CONFIGURATION_FAILURE = "隔離PostgreSQL接続設定が不正です"

_Result = TypeVar("_Result")


class IsolatedPostgresFixtureFailure(RuntimeError):
    """隔離PostgreSQL fixtureが公開する非secretな失敗。"""


def _run_fixture_operation(
    operation: Callable[[], _Result], diagnostic: str
) -> _Result:
    """driver例外を保持せず、fixture境界の固定診断だけを返す。"""
    try:
        return operation()
    except Exception:
        pass
    raise IsolatedPostgresFixtureFailure(diagnostic)


def _fail_fixture_operation(error: IsolatedPostgresFixtureFailure) -> None:
    """driver由来のtracebackを含めず、固定診断だけをpytestへ渡す。"""
    pytest.fail(str(error), pytrace=False)


def resolve_test_password(environ: Mapping[str, str]) -> str:
    """呼出側が明示注入した試験用認証情報だけを使用する。"""
    password = environ.get(_TEST_PASSWORD_ENV)
    if password is None:
        return _CI_ISOLATED_PASSWORD
    if not password:
        raise ValueError("YURA_TEST_POSTGRES_PASSWORDは空にできません")
    return password


def resolve_test_port(environ: Mapping[str, str]) -> int:
    """試験用portを固定診断の境界で整数化する。"""
    raw_port = environ.get("YURA_TEST_POSTGRES_PORT", "58439")
    return _run_fixture_operation(
        lambda: int(raw_port), _CONNECTION_CONFIGURATION_FAILURE
    )


def subprocess_test_environment(
    environ: Mapping[str, str], *, path: str, pythonpath: str
) -> dict[str, str]:
    """縮小した子process環境へ試験用passwordだけを明示継承する。"""
    child_environ = {"PATH": path, "PYTHONPATH": pythonpath}
    password = environ.get(_TEST_PASSWORD_ENV)
    if password is not None:
        child_environ[_TEST_PASSWORD_ENV] = password
    return child_environ


def temporary_database_name() -> str:
    """本番databaseと衝突しない試験専用database名を返す。"""
    return "yura_test_" + uuid4().hex


@pytest.fixture
def endpoint() -> Iterator[PostgresEndpoint]:
    host = os.environ.get("YURA_TEST_POSTGRES_HOST") or os.environ.get("YURA_TEST_POSTGRES_SOCKET")
    if not host:
        if os.environ.get("YURA_REQUIRE_POSTGRES") == "1":
            pytest.fail("必須の隔離PostgreSQL接続先が指定されていません")
        pytest.skip("隔離PostgreSQLのソケットが明示されていません")
    psycopg: Any = import_module("psycopg")
    database = temporary_database_name()
    user = os.environ.get("YURA_TEST_POSTGRES_USER", getpass.getuser())
    try:
        port = resolve_test_port(os.environ)
    except IsolatedPostgresFixtureFailure as error:
        _fail_fixture_operation(error)
    password = resolve_test_password(os.environ)
    try:
        admin = _run_fixture_operation(
            lambda: psycopg.connect(
                host=host,
                port=port,
                dbname="postgres",
                user=user,
                password=password,
                passfile="/dev/null",
                sslmode="disable",
                connect_timeout=2,
                autocommit=True,
            ),
            _ADMIN_CONNECTION_FAILURE,
        )
    except IsolatedPostgresFixtureFailure as error:
        _fail_fixture_operation(error)

    try:
        _run_fixture_operation(
            lambda: admin.execute(
                psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(database))
            ),
            _DATABASE_PREPARATION_FAILURE,
        )
    except IsolatedPostgresFixtureFailure as error:
        try:
            _run_fixture_operation(admin.close, _CONNECTION_CLEANUP_FAILURE)
        except IsolatedPostgresFixtureFailure as cleanup_error:
            _fail_fixture_operation(cleanup_error)
        _fail_fixture_operation(error)

    try:
        yield PostgresEndpoint(host, port, database, user, password, "disable")
    finally:
        try:
            _run_fixture_operation(
                lambda: admin.execute(
                    psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        psycopg.sql.Identifier(database)
                    )
                ),
                _DATABASE_CLEANUP_FAILURE,
            )
        except IsolatedPostgresFixtureFailure as error:
            try:
                _run_fixture_operation(admin.close, _CONNECTION_CLEANUP_FAILURE)
            except IsolatedPostgresFixtureFailure as cleanup_error:
                _fail_fixture_operation(cleanup_error)
            _fail_fixture_operation(error)
        try:
            _run_fixture_operation(admin.close, _CONNECTION_CLEANUP_FAILURE)
        except IsolatedPostgresFixtureFailure as error:
            _fail_fixture_operation(error)
