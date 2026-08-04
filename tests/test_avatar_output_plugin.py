from __future__ import annotations

from typing import cast

import pytest

from app.bootstrap.plugin_registration import register_optional_plugin_from_factory
from app.core.plugins import PluginManager, SystemClock
from app.ports.avatar_output import AvatarGazeIntent, AvatarOutputPort
from app.shared.contracts.plugins.runtime import PluginContext


class FakeAvatarAdapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.expressions: list[str] = []
        self.gestures: list[str] = []
        self.gazes: list[AvatarGazeIntent] = []

    async def set_expression(self, expression: str) -> None:
        if self.fail:
            raise RuntimeError("avatar runtime unavailable")
        self.expressions.append(expression)

    async def play_gesture(self, gesture: str) -> None:
        if self.fail:
            raise RuntimeError("avatar runtime unavailable")
        self.gestures.append(gesture)

    async def set_gaze(self, gaze: AvatarGazeIntent) -> None:
        if self.fail:
            raise RuntimeError("avatar runtime unavailable")
        self.gazes.append(gaze)


class UnusedLlmGateway:
    async def generate_response(self, request: object) -> str:
        raise AssertionError("avatar output must not call the LLM gateway")


class UnusedActivityGateway:
    def register(self, activity: object) -> object:
        raise AssertionError("avatar output must not register activities")


def create_initialized_plugin(
    adapter: FakeAvatarAdapter,
) -> tuple[PluginManager, AvatarOutputPort]:
    manager = PluginManager()
    plugin = register_optional_plugin_from_factory(
        manager,
        plugin_id="avatar_output",
        module="app.plugins.avatar_output",
        enabled=True,
        services={"avatar_output": adapter},
    )
    assert plugin is not None
    manager.initialize_enabled_plugins(
        PluginContext(
            llm_gateway=UnusedLlmGateway(),
            activity_gateway=UnusedActivityGateway(),
            clock=SystemClock(),
            configuration={},
            capability_reporter=manager,
        ),
        {"avatar_output": True},
    )
    return manager, cast(AvatarOutputPort, plugin)


@pytest.mark.asyncio
async def test_avatar_output_plugin_is_registered_by_generic_factory() -> None:
    adapter = FakeAvatarAdapter()
    manager, output = create_initialized_plugin(adapter)

    assert manager.is_capability_available(
        "output.avatar.expression",
        "avatar_output",
    )
    assert manager.is_capability_available(
        "output.avatar.gesture",
        "avatar_output",
    )
    assert manager.is_capability_available(
        "output.avatar.gaze",
        "avatar_output",
    )

    gaze = AvatarGazeIntent(
        target="viewer",
        behavior="maintain",
        intensity=0.8,
    )
    await output.set_expression("happy")
    await output.play_gesture("small_nod")
    await output.set_gaze(gaze)

    assert adapter.expressions == ["happy"]
    assert adapter.gestures == ["small_nod"]
    assert adapter.gazes == [gaze]


@pytest.mark.asyncio
async def test_avatar_output_failure_marks_all_capabilities_unavailable() -> None:
    manager, output = create_initialized_plugin(FakeAvatarAdapter(fail=True))

    with pytest.raises(RuntimeError, match="avatar runtime unavailable"):
        await output.set_expression("happy")

    assert not manager.is_capability_available(
        "output.avatar.expression",
        "avatar_output",
    )
    assert not manager.is_capability_available(
        "output.avatar.gesture",
        "avatar_output",
    )
    assert not manager.is_capability_available(
        "output.avatar.gaze",
        "avatar_output",
    )
