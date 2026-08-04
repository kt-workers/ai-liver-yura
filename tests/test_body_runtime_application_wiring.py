from __future__ import annotations

from typing import cast

import pytest

from app.bootstrap import runtime as runtime_bootstrap
from app.bootstrap.body_runtime_setup import (
    clear_bound_body_runtime,
    create_bound_body_runtime_from_env,
    install_body_aware_runtime_components,
)
from app.domain.actions import ActionPlan, ActionType
from app.domain.avatar_performance import AvatarPerformancePlan
from app.domain.body import (
    BodyActivityContext,
    BodyExpressionRequest,
    EmbodiedExpressionIntent,
    SpeechPresentationRequest,
)
from app.domain.body_runtime import BodyRuntimeSnapshot
from app.ports.avatar_output import (
    AvatarGazeIntent,
    AvatarOutputPort,
    bind_avatar_output,
)
from app.ports.body_subsystem import (
    BodySubsystemPort,
    bind_body_subsystem,
    get_bound_body_subsystem,
)
from app.runtime.avatar_performance_action_planner import (
    AvatarPerformanceActionPlanner,
)
from app.runtime.avatar_performance_character_service import (
    AvatarPerformanceCharacterLlmService,
)
from app.runtime.body_runtime import BodyRuntime
from app.usecases import ExecuteActionUsecase


class FakeAvatarOutput:
    def __init__(self) -> None:
        self.performances: list[AvatarPerformancePlan] = []
        self.expressions: list[str] = []
        self.gestures: list[str] = []

    async def submit_performance(self, performance: AvatarPerformancePlan) -> None:
        self.performances.append(performance)

    async def set_expression(self, expression: str) -> None:
        self.expressions.append(expression)

    async def play_gesture(self, gesture: str) -> None:
        self.gestures.append(gesture)

    async def set_gaze(self, gaze: AvatarGazeIntent) -> None:
        del gaze


class FakeBodySubsystem:
    def __init__(self) -> None:
        self.contexts: list[BodyActivityContext] = []
        self.expressions: list[BodyExpressionRequest] = []
        self.speeches: list[SpeechPresentationRequest] = []
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def update_activity_context(self, context: BodyActivityContext) -> None:
        self.contexts.append(context)

    async def request_expression(self, request: BodyExpressionRequest) -> None:
        self.expressions.append(request)

    async def present_speech(self, request: SpeechPresentationRequest) -> None:
        self.speeches.append(request)

    async def snapshot(self) -> BodyRuntimeSnapshot:
        return BodyRuntimeSnapshot(running=self.started)


@pytest.fixture(autouse=True)
def reset_runtime_bindings(monkeypatch: pytest.MonkeyPatch) -> None:
    bind_avatar_output(None)
    bind_body_subsystem(None)
    monkeypatch.delenv("YURA_BODY_RUNTIME_ENABLED", raising=False)
    yield
    bind_avatar_output(None)
    bind_body_subsystem(None)


def test_install_body_aware_runtime_components_keeps_activity_pipeline() -> None:
    install_body_aware_runtime_components()

    assert runtime_bootstrap.ActionPlanner is AvatarPerformanceActionPlanner
    assert (
        runtime_bootstrap.CharacterLlmService
        is AvatarPerformanceCharacterLlmService
    )


def test_create_bound_body_runtime_uses_initialized_avatar_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avatar = FakeAvatarOutput()
    bind_avatar_output(cast(AvatarOutputPort, avatar))
    monkeypatch.setenv("YURA_BODY_RUNTIME_ENABLED", "1")
    monkeypatch.setenv("YURA_BODY_TICK_HZ", "24")

    body = create_bound_body_runtime_from_env()

    assert isinstance(body, BodyRuntime)
    assert get_bound_body_subsystem() is body
    clear_bound_body_runtime()
    assert get_bound_body_subsystem() is None


def test_create_bound_body_runtime_skips_without_avatar_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YURA_BODY_RUNTIME_ENABLED", "1")

    assert create_bound_body_runtime_from_env() is None
    assert get_bound_body_subsystem() is None


@pytest.mark.asyncio
async def test_execute_action_routes_activity_context_and_expression_to_late_binding() -> None:
    usecase = ExecuteActionUsecase()
    body = FakeBodySubsystem()
    bind_body_subsystem(cast(BodySubsystemPort, body))
    context = BodyActivityContext(
        source_activity_id="activity-1",
        attention_target="conversation_partner",
        engagement=0.8,
    )
    request = BodyExpressionRequest(
        source_activity_id="activity-1",
        output_unit_id="output-1",
        expression=EmbodiedExpressionIntent(
            attitude="rejection",
            intensity=0.8,
            agreement=-0.9,
            approach=-0.5,
        ),
        facial_expression="disgusted",
        facial_intensity=0.9,
    )

    await usecase.execute(
        ActionPlan(
            action_type=ActionType.CHANGE_EXPRESSION,
            text="disgusted",
            source_activity_id="activity-1",
            output_unit_id="output-1",
            metadata={
                "body_activity_context": context,
                "body_expression_request": request,
            },
        )
    )
    await usecase.execute(
        ActionPlan(
            action_type=ActionType.MOVE,
            text="head_shake",
            source_activity_id="activity-1",
            output_unit_id="output-1",
            metadata={"body_expression_request": request},
        )
    )

    assert body.contexts == [context]
    assert body.expressions == [request]


@pytest.mark.asyncio
async def test_speech_presentation_uses_body_clock_without_owning_tts() -> None:
    body = FakeBodySubsystem()
    usecase = ExecuteActionUsecase(body_subsystem=cast(BodySubsystemPort, body))
    action = ActionPlan(
        action_type=ActionType.SPEAK,
        text="うん、そうだね。",
        source_activity_id="activity-1",
        output_unit_id="output-1",
    )

    await usecase._present_speech_to_body(action)

    assert len(body.speeches) == 1
    presentation = body.speeches[0]
    assert presentation.source_activity_id == "activity-1"
    assert presentation.output_unit_id == "output-1"
    assert presentation.audio_reference.startswith("estimated://speech/")
    assert presentation.duration_ms >= 100
