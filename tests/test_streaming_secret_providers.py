from __future__ import annotations

from subsystems.streaming.config import (
    STREAMING_OBS_PASSWORD,
    CompositeSecretProvider,
    EnvironmentSecretProvider,
    NullSecretProvider,
    StaticSecretProvider,
)


def test_null_and_blank_secrets_are_unset() -> None:
    assert NullSecretProvider().get_secret("anything") is None
    assert StaticSecretProvider({"empty": "  "}).get_secret("empty") is None


def test_static_provider_defensively_copies_and_redacts_values() -> None:
    values = {"named-secret": "fixture-only-value"}
    provider = StaticSecretProvider(values)
    values["named-secret"] = "changed"

    assert provider.get_secret("named-secret") == "fixture-only-value"
    assert "fixture-only-value" not in repr(provider)


def test_environment_provider_supports_standard_name_and_legacy_alias() -> None:
    standard = EnvironmentSecretProvider(
        {STREAMING_OBS_PASSWORD: "standard-value", "OBS_WEBSOCKET_PASSWORD": "old"}
    )
    alias = EnvironmentSecretProvider(
        {"OBS_WEBSOCKET_PASSWORD": "legacy-value"}
    )

    assert standard.get_secret(STREAMING_OBS_PASSWORD) == "standard-value"
    assert alias.get_secret(STREAMING_OBS_PASSWORD) == "legacy-value"
    assert "legacy-value" not in repr(alias)


def test_environment_provider_defensively_copies_explicit_mapping() -> None:
    environ = {STREAMING_OBS_PASSWORD: "fixture-only-value"}
    provider = EnvironmentSecretProvider(environ)

    environ[STREAMING_OBS_PASSWORD] = "changed-after-construction"

    assert provider.get_secret(STREAMING_OBS_PASSWORD) == "fixture-only-value"


def test_composite_uses_first_available_provider_without_exposing_values() -> None:
    provider = CompositeSecretProvider(
        (
            NullSecretProvider(),
            StaticSecretProvider({"name": "first-value"}),
            StaticSecretProvider({"name": "second-value"}),
        )
    )

    assert provider.get_secret("name") == "first-value"
    assert "first-value" not in repr(provider)
