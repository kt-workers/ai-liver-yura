"""隔離PostgreSQL fixtureの認証情報境界を検証する。"""

from pathlib import Path

import pytest

from app.infrastructure.persistence.postgresql_connection import PostgresEndpoint
from tests.infrastructure.postgresql import conftest


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
