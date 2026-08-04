from typing import cast

import pytest

from app.domain.actions import ActionPlan, ActionType
from app.domain.avatar_performance import (
    AvatarExpressionIntent,
    AvatarGestureIntent,
    AvatarPerformancePlan,
    AvatarPerformanceSegment,
)
from app.ports.avatar_output import (
    AvatarGazeIntent,
    AvatarOutputPort,
    bind_avatar_output,
)
from app.usecases import ExecuteActionUsecase


class FakeAvatarOutput:
    def __init__(
        self,
        *,
        fail: bool = False,
        fail_performance: bool = False,
    ) -> None:
        self.fail = fail
        self.fail_performance = fail_performance
        self.performances: list[AvatarPerformancePlan] = []
        self.expressions: list[str] = []
        self.gestures: list[str] = []
        self.gazes: list[AvatarGazeIntent] = []

    async def submit_performance(self, performance: AvatarPerformancePlan) -> None:
        if self.fail or self.fail_performance:
            raise RuntimeError("avatar performance unavailable")
        self.performances.append(performance)

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


def performance_plan() -> AvatarPerformancePlan:
    return AvatarPerformancePlan(
        performance_id="perf-001",
        source_activity_id="activity-001",
        output_unit_id="output-001",
        priority=100,
        segments=(
            AvatarPerformanceSegment(
                expression=AvatarExpressionIntent("curious", 0.7),
                gesture=AvatarGestureIntent("head_tilt", 0.4),
                gaze=AvatarGazeIntent("viewer", intensity=0.8),
            ),
        ),
    )


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
async def test_execute_action_submits_performance_once_and_skips_individual_actions() -> None:
    fake = FakeAvatarOutput()
    usecase = ExecuteActionUsecase(
        avatar_output=cast(AvatarOutputPort, fake)
    )
    performance = performance_plan()
    shared_metadata = {
        "avatar_performance_id": performance.performance_id,
        "avatar_performance_managed": True,
    }

    await usecase.execute(
        ActionPlan(
            action_type=ActionType.CHANGE_EXPRESSION,
            text="curious",
            metadata={
                **shared_metadata,
                "avatar_performance_plan": performance,
            },
        )
    )
    await usecase.execute(
        ActionPlan(
            action_type=ActionType.MOVE,
            text="head_tilt",
            metadata=shared_metadata,
        )
    )

    assert fake.performances == [performance]
    assert fake.expressions == []
    assert fake.gestures == []


@pytest.mark.asyncio
async def test_execute_action_falls_back_when_performance_submission_fails() -> None:
    fake = FakeAvatarOutput(fail_performance=True)
    usecase = ExecuteActionUsecase(
        avatar_output=cast(AvatarOutputPort, fake)
    )
    performance = performance_plan()

    await usecase.execute(
        ActionPlan(
            action_type=ActionType.CHANGE_EXPRESSION,
            text="curious",
            metadata={
                "avatar_performance_id": performance.performance_id,
                "avatar_performance_managed": True,
                "avatar_performance_plan": performance,
            },
        )
    )

    assert fake.performances == []
    assert fake.expressions == ["curious"]


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
