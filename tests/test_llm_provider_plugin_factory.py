from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.plugins import PluginContext, PluginManager, SystemClock
from app.plugins.llm_provider import (
    LlmProviderPlugin,
    LlmProviderPluginFactory,
    plugin_factory,
)
from app.shared.contracts.plugins.factory import PluginFactoryContext


class _Generator:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[object] = []

    async def generate_response(self, request: object) -> str:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return "generated"


class _Gateway:
    async def generate_response(self, request: object) -> str:
        return ""

    def register(self, activity: object) -> object:
        return activity


def _create_plugin(
    *,
    role: object = "character",
    configured_available: object = True,
    generator: object = None,
) -> LlmProviderPlugin:
    if generator is None:
        generator = _Generator()
    return plugin_factory.create_plugin(
        PluginFactoryContext(
            configuration={
                "role": role,
                "configured_available": configured_available,
            },
            services={"response_generator": generator},
        )
    )


def _initialize(plugin: LlmProviderPlugin) -> PluginManager:
    manager = PluginManager()
    manager.register(plugin)
    gateway = _Gateway()
    manager.initialize_enabled_plugins(
        PluginContext(
            llm_gateway=gateway,
            activity_gateway=gateway,
            clock=SystemClock(),
            configuration={},
            capability_reporter=manager,
        ),
        {plugin.plugin_id: True},
    )
    return manager


@pytest.mark.asyncio
async def test_factory_creates_role_plugin_and_delegates_to_shared_generator() -> None:
    generator = _Generator()
    plugin = _create_plugin(
        role="situation_evaluator",
        configured_available=True,
        generator=generator,
    )
    manager = _initialize(plugin)
    request = object()

    response = await plugin.generate_response(request)

    assert plugin.plugin_id == "llm_provider.situation_evaluator"
    assert response == "generated"
    assert generator.requests == [request]
    assert manager.is_capability_available("llm.provider", plugin.plugin_id)
    assert manager.is_capability_available(
        "llm.provider.situation_evaluator",
        plugin.plugin_id,
    )


@pytest.mark.asyncio
async def test_factory_preserves_configured_unavailable_behavior() -> None:
    plugin = _create_plugin(configured_available=False)
    manager = _initialize(plugin)

    assert plugin.available_capabilities() == frozenset()
    assert not manager.is_capability_available("llm.provider", plugin.plugin_id)
    with pytest.raises(RuntimeError, match=r"llm_provider\.character\.unavailable"):
        await plugin.generate_response(object())


@pytest.mark.asyncio
async def test_factory_created_plugin_revokes_all_capabilities_on_failure() -> None:
    plugin = _create_plugin(generator=_Generator(error=OSError("offline")))
    manager = _initialize(plugin)

    with pytest.raises(OSError, match="offline"):
        await plugin.generate_response(object())

    assert not manager.is_capability_available("llm.provider", plugin.plugin_id)
    assert not manager.is_capability_available(
        "llm.provider.character",
        plugin.plugin_id,
    )


@pytest.mark.parametrize(
    ("configuration", "error_type", "message"),
    [
        (
            {"configured_available": True},
            TypeError,
            "llm_provider.role must be str",
        ),
        (
            {"role": "", "configured_available": True},
            ValueError,
            "llm_provider.role must not be empty",
        ),
        (
            {"role": 123, "configured_available": True},
            TypeError,
            "llm_provider.role must be str",
        ),
        (
            {"role": "default"},
            TypeError,
            "llm_provider.configured_available must be bool",
        ),
        (
            {"role": "default", "configured_available": "yes"},
            TypeError,
            "llm_provider.configured_available must be bool",
        ),
    ],
)
def test_factory_rejects_invalid_configuration(
    configuration: dict[str, object],
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        LlmProviderPluginFactory().create_plugin(
            PluginFactoryContext(
                configuration=configuration,
                services={"response_generator": _Generator()},
            )
        )


@pytest.mark.parametrize(
    "services",
    [
        {},
        {"response_generator": object()},
    ],
)
def test_factory_rejects_missing_or_invalid_generator(
    services: dict[str, object],
) -> None:
    with pytest.raises(
        TypeError,
        match=r"llm_provider\.response_generator must implement generate_response\(\)",
    ):
        LlmProviderPluginFactory().create_plugin(
            PluginFactoryContext(
                configuration={
                    "role": "default",
                    "configured_available": True,
                },
                services=services,
            )
        )


def test_factory_does_not_import_concrete_llm_adapters() -> None:
    path = Path(__file__).parents[1] / "app/plugins/llm_provider/factory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(not name.startswith("app.adapters") for name in imports)
