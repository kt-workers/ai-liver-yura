"""#709 の本番Speech deployment factoryに固有の資源境界を確認する。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.composition.presentation_notification import CoreSpeechProductionOwnerConnection
from app.composition.speech_deployment import production_speech_deployment_registry
from app.composition.speech_deployment_factory import (
    ProductionSpeechDeploymentPortFactory,
    SpeechDeploymentFactoryError,
    SpeechDeploymentOwnerConnections,
    speech_tts_request_id,
)
from app.config.layered import ConfigurationError


class _Lease:
    def __init__(self, events: list[str], name: str, *, fail: bool = False) -> None:
        self._events, self._name, self._fail = events, name, fail

    async def close(self) -> None:
        self._events.append(self._name)
        if self._fail:
            raise RuntimeError("非公開の失敗")


class _Provider:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def release(self) -> None:
        self._events.append("provider.release")


@pytest.mark.asyncio
async def test_partial_acquisition_cleanup_is_reverse_order() -> None:
    events: list[str] = []
    await ProductionSpeechDeploymentPortFactory._cleanup(
        cast(Any, _Provider(events)),
        cast(Any, _Lease(events, "tts.close")),
        cast(Any, _Lease(events, "presentation.close")),
    )
    assert events == ["presentation.close", "tts.close", "provider.release"]


@pytest.mark.asyncio
async def test_cleanup_failure_never_becomes_success() -> None:
    with pytest.raises(SpeechDeploymentFactoryError, match="回収"):
        await ProductionSpeechDeploymentPortFactory._cleanup(
            cast(Any, _Provider([])),
            cast(Any, _Lease([], "tts.close", fail=True)),
            None,
        )


def test_tts_request_id_uses_exact_public_identity_material() -> None:
    request = SimpleNamespace(
        candidate_id="candidate", candidate_generation=2, performance_generation=3
    )
    connection = SimpleNamespace(mapping=SimpleNamespace(mapping_id="mapping", mapping_revision=4))
    first = speech_tts_request_id(cast(Any, request), cast(Any, connection), "voice", 5)
    second = speech_tts_request_id(cast(Any, request), cast(Any, connection), "voice", 5)
    changed = speech_tts_request_id(cast(Any, request), cast(Any, connection), "voice", 6)
    assert first == second
    assert first.startswith("tts-") and len(first) == 68
    assert changed != first


def test_registry_rejects_untrusted_factory_bundle() -> None:
    with pytest.raises(ConfigurationError):
        production_speech_deployment_registry({"production": object()})


def test_owner_connection_is_resolved_after_cognition_and_reference_exist() -> None:
    cognition, reference = object(), object()
    owner = object.__new__(CoreSpeechProductionOwnerConnection)
    object.__setattr__(owner, "cognition", cognition)
    object.__setattr__(owner, "reference", reference)
    connections = object.__new__(SpeechDeploymentOwnerConnections)
    object.__setattr__(connections, "owner_connection", lambda c, r: owner)
    factory = object.__new__(ProductionSpeechDeploymentPortFactory)
    object.__setattr__(factory, "_connections", connections)
    assert factory._owner_connection(cognition, reference) is owner


def test_owner_connection_rejects_different_s2_graph() -> None:
    owner = object.__new__(CoreSpeechProductionOwnerConnection)
    object.__setattr__(owner, "cognition", object())
    object.__setattr__(owner, "reference", object())
    connections = object.__new__(SpeechDeploymentOwnerConnections)
    object.__setattr__(connections, "owner_connection", lambda c, r: owner)
    factory = object.__new__(ProductionSpeechDeploymentPortFactory)
    object.__setattr__(factory, "_connections", connections)
    with pytest.raises(SpeechDeploymentFactoryError, match="Owner graph"):
        factory._owner_connection(object(), object())


@pytest.mark.asyncio
async def test_returned_release_joins_repeated_calls_once() -> None:
    events: list[str] = []
    release = ProductionSpeechDeploymentPortFactory._release(
        cast(Any, _Provider(events)),
        cast(Any, _Lease(events, "tts.close")),
        cast(Any, _Lease(events, "presentation.close")),
    )
    await release()
    await release()
    assert events == ["presentation.close", "tts.close", "provider.release"]
