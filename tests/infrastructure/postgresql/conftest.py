"""各試験が専用の空DBを所有し、終了時に回収する。"""

import getpass
import os
from collections.abc import Iterator, Mapping
from importlib import import_module
from typing import Any
from uuid import uuid4

import pytest

from app.infrastructure.persistence.postgresql_connection import PostgresEndpoint

_TEST_PASSWORD_ENV = "YURA_TEST_POSTGRES_PASSWORD"
_CI_ISOLATED_PASSWORD = "isolated-test-no-auth"


def resolve_test_password(environ: Mapping[str, str]) -> str:
    """呼出側が明示注入した試験用認証情報だけを使用する。"""
    password = environ.get(_TEST_PASSWORD_ENV)
    if password is None:
        return _CI_ISOLATED_PASSWORD
    if not password:
        raise ValueError("YURA_TEST_POSTGRES_PASSWORDは空にできません")
    return password


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
    port = int(os.environ.get("YURA_TEST_POSTGRES_PORT", "58439"))
    password = resolve_test_password(os.environ)
    with psycopg.connect(
        host=host,
        port=port,
        dbname="postgres",
        user=user,
        password=password,
        passfile="/dev/null",
        sslmode="disable",
        connect_timeout=2,
        autocommit=True,
    ) as admin:
        admin.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(database))
        )
        try:
            yield PostgresEndpoint(host, port, database, user, password, "disable")
        finally:
            admin.execute(
                psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(database)
                )
            )
