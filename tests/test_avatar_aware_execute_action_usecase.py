from typing import cast

import pytest

from app.domain.actions import ActionPlan, ActionType
from app.ports.avatar_output import (
    AvatarGazeIntent,
    AvatarOutputPort,
    bind_avatar_output,
)
from app.usecases import ExecuteActionUsecase


class FakeAvatarOutput:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.expressions: list[str] = []
        self.gestures: list[str] = []
        self.gazes: list[AvatarGazeIntent] = []

    async def set_expression(self, expression: str) -> None:
        if self.fail:
            raise RuntimeError("avatar offline")
        self.expressions.append(expression)

    async def play_gesture(self, gesture: str) -> None:
        if self.fail:
            raise RuntimeError("avatar offline")
        self.gestures.append(gesture)

    async def set_gaze(self, gaze: AvatarGazeIntent) -> None:
        if self.fail:
            raise RuntimeError("avatar offline")
        self.gazes.append(gaze)


@pytest.fixture(autouse=True)
def reset_avatar_output_binding() -> None:
    bind_avatar_output(None)
    yield
    bind_avatar_output(None)


@pytest.mark.asyncio
async def test_execute_action_routes_llm_expression_and_move_to_avatar() -> None:
    fake = FakeAvatarOutput()
    usecase = ExecuteActionUsecase(
        avatar_output=cast(AvatarOutputPort, fake)
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
async def test_execute_action_uses_composition_root_binding_by_default() -> None:
    fake = FakeAvatarOutput()
    bind_avatar_output(cast(AvatarOutputPort, fake))
    usecase = ExecuteActionUsecase()

    await usecase.execute(
        ActionPlan(
            action_type=ActionType.CHANGE_EXPRESSION,
            text="happy",
        )
    )

    assert fake.expressions == ["happy"]


@pytest.mark.asyncio
async def test_execute_action_keeps_core_running_when_avatar_fails() -> None:
    fake = FakeAvatarOutput(fail=True)
    usecase = ExecuteActionUsecase(
        avatar_output=cast(AvatarOutputPort, fake)
    )

    result = await usecase.execute(
        ActionPlan(
            action_type=ActionType.CHANGE_EXPRESSION,
            text="happy",
        )
    )

    assert result is None
