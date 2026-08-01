from __future__ import annotations

import pytest

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionType
from app.domain.activities import Activity
from app.domain.character_response import VoiceIntent
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_state import AgentState
from app.runtime.planned_activity_queue import PlannedActivity, PlannedActivityQueue
from app.usecases import ExecuteActionUsecase


class FailingSpeechSynthesizer:
    async def synthesize(
        self, text: str, voice_intent: VoiceIntent | None = None
    ) -> bytes:
        raise RuntimeError("VOICEVOX unavailable")


class FakeAudioPlayer:
    async def play(self, audio_data: bytes) -> None:
        return None


class RecordingConversationOutputPublisher:
    def __init__(self) -> None:
        self.outputs: list[str] = []

    async def publish_text(self, *, kind: str, text: str, action_id: str) -> None:
        self.outputs.append(text)


class SpeakActionPlanner:
    def __init__(self, text: str) -> None:
        self.text = text

    async def plan(self, activity: Activity) -> ActionPlanGroup:
        return ActionPlanGroup(
            action_plans=[
                ActionPlan(
                    action_type=ActionType.SPEAK,
                    text=self.text,
                    source_activity_id=activity.activity_id,
                )
            ],
            source_activity_id=activity.activity_id,
        )


class RecordingAgentLifeService:
    def __init__(self) -> None:
        self.recorded_outputs: list[tuple[str, str]] = []
        self.completed_topics: list[str] = []
        self._agent_state = AgentState()

    @property
    def agent_state(self) -> AgentState:
        return self._agent_state

    def sync_from_activity_manager(self) -> AgentState:
        return self._agent_state

    def record_autonomous_output(
        self,
        *,
        activity_id: str,
        text: str,
        context: dict[str, object] | None = None,
    ) -> object:
        self.recorded_outputs.append((activity_id, text))
        return object()

    def should_complete_autonomous_activity(self, *, activity_id: str) -> bool:
        return False

    def complete_autonomous_topic(self, *, activity_id: str) -> None:
        self.completed_topics.append(activity_id)


@pytest.mark.asyncio
async def test_voice_failure_still_records_autonomous_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_wait(duration: float) -> None:
        return None

    monkeypatch.setattr(
        "app.usecases.execute_action_usecase.asyncio.sleep",
        no_wait,
    )
    activity_manager = ActivityManager()
    autonomous = activity_manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.CURIOSITY_PEAK,
            priority=8,
            payload={"selected_topic": "音声非依存の確認"},
        )
    )
    queue = PlannedActivityQueue()
    queue.put(PlannedActivity(activity=autonomous))
    output = RecordingConversationOutputPublisher()
    usecase = ExecuteActionUsecase(
        speech_synthesizer=FailingSpeechSynthesizer(),
        audio_player=FakeAudioPlayer(),
        conversation_output_publisher=output,
    )
    life_service = RecordingAgentLifeService()
    executor = ActivityExecutorThread(
        planned_activity_queue=queue,
        action_planner=SpeakActionPlanner("音声がなくても自律発話は成立するよ。"),  # type: ignore[arg-type]
        action_scheduler=ActionScheduler(usecase),
        activity_manager=activity_manager,
        agent_life_service=life_service,  # type: ignore[arg-type]
    )

    result = await executor.run_once()

    assert result is not None
    assert output.outputs == ["音声がなくても自律発話は成立するよ。"]
    assert life_service.recorded_outputs == [
        (autonomous.activity_id, "音声がなくても自律発話は成立するよ。")
    ]
