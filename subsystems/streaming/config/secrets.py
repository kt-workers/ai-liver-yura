"""Secret lookup abstractions without repository-owned secret values."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Protocol

from subsystems.streaming.config.obs import STREAMING_OBS_PASSWORD
from subsystems.streaming.config.youtube import (
    STREAMING_YOUTUBE_CLIENT_SECRET_PATH,
    STREAMING_YOUTUBE_TOKEN_PATH,
)

DEFAULT_SECRET_ALIASES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        STREAMING_YOUTUBE_CLIENT_SECRET_PATH: ("YOUTUBE_CLIENT_SECRET_PATH",),
        STREAMING_YOUTUBE_TOKEN_PATH: ("YOUTUBE_TOKEN_PATH",),
        STREAMING_OBS_PASSWORD: ("OBS_WEBSOCKET_PASSWORD",),
    }
)


class SecretProvider(Protocol):
    def get_secret(self, name: str) -> str | None: ...


class NullSecretProvider:
    def get_secret(self, name: str) -> None:
        del name
        return None

    def __repr__(self) -> str:
        return "NullSecretProvider()"


class EnvironmentSecretProvider:
    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        *,
        aliases: Mapping[str, Sequence[str]] = DEFAULT_SECRET_ALIASES,
    ) -> None:
        self._environ = (
            None if environ is None else MappingProxyType(dict(environ))
        )
        self._aliases = MappingProxyType(
            {name: tuple(values) for name, values in aliases.items()}
        )

    def get_secret(self, name: str) -> str | None:
        environ = os.environ if self._environ is None else self._environ
        for candidate in (name, *self._aliases.get(name, ())):
            value = environ.get(candidate)
            if value is not None and value.strip():
                return value
        return None

    def __repr__(self) -> str:
        return "EnvironmentSecretProvider()"


class StaticSecretProvider:
    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = MappingProxyType(dict(values))

    def get_secret(self, name: str) -> str | None:
        value = self._values.get(name)
        return value if value is not None and value.strip() else None

    def __repr__(self) -> str:
        return f"StaticSecretProvider(names={tuple(sorted(self._values))!r})"


class CompositeSecretProvider:
    def __init__(self, providers: Sequence[SecretProvider]) -> None:
        self._providers = tuple(providers)

    def get_secret(self, name: str) -> str | None:
        for provider in self._providers:
            value = provider.get_secret(name)
            if value is not None and value.strip():
                return value
        return None

    def __repr__(self) -> str:
        return f"CompositeSecretProvider(count={len(self._providers)})"
