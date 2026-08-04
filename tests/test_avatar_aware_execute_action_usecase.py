from typing import cast

import pytest

from app.domain.actions import ActionPlan, ActionType
from app.plugins.avatar_output import AvatarOutputPlugin
from app.usecases import ExecuteActionUsecase


class FakeAvatarPlugin:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.expressions: list[str] = []
        self.gestures: list[str] = []

    async def set_expression(self, expression: str) -> None:
        if self.fail:
            raise RuntimeError("avatar offline")
        self.expressions.append(expression)

    async def play_gesture(self, gesture: str) -> None:
        if self.fail:
            raise RuntimeError("avatar offline")
        self.gestures.append(gesture)


@pytest.mark.asyncio
async def test_execute_action_routes_llm_expression_and_move_to_avatar() -> None:
    fake = FakeAvatarPlugin()
    usecase = ExecuteActionUsecase(
        avatar_output_plugin=cast(AvatarOutputPlugin, fake)
    )

    await usecase.execute(
        ActionPlan(
            action_type=ActionType.CHANGE_EXPRESSION,
            text="curious",
        )
    )
    await usecase.execute(
        ActionPlan(
            action_type=ActionType.MOVE,
            text="head_tilt",
        )
    )

    assert fake.expressions == ["curious"]
    assert fake.gestures == ["head_tilt"]


@pytest.mark.asyncio
async def test_execute_action_keeps_core_running_when_avatar_fails() -> None:
    fake = FakeAvatarPlugin(fail=True)
    usecase = ExecuteActionUsecase(
        avatar_output_plugin=cast(AvatarOutputPlugin, fake)
    )

    result = await usecase.execute(
        ActionPlan(
            action_type=ActionType.CHANGE_EXPRESSION,
            text="happy",
        )
    )

    assert result is None
