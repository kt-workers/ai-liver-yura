from __future__ import annotations

from app.domain.topic import InterruptedTopic
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_state_synchronizer import ActivityStateSynchronizer
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState


class RecordingActivityStateSynchronizer(ActivityStateSynchronizer):
    def __init__(self, activity_manager: ActivityManager) -> None:
        super().__init__(activity_manager)
        self.calls: list[InterruptedTopic | None] = []

    def synchronize(
        self,
        state: AgentState,
        *,
        autonomous_topic: InterruptedTopic | None = None,
    ) -> AgentState:
        self.calls.append(autonomous_topic)
        return super().synchronize(
            state,
            autonomous_topic=autonomous_topic,
        )


def test_agent_life_service_delegates_activity_state_synchronization() -> None:
    activity_manager = ActivityManager()
    synchronizer = RecordingActivityStateSynchronizer(activity_manager)
    service = AgentLifeService(
        activity_manager,
        activity_state_synchronizer=synchronizer,
    )
    topic = service.interrupt_autonomous_topic(
        activity_id="activity-1",
        fallback_text="続きを話したい",
    )

    state = service.sync_from_activity_manager()

    assert synchronizer.calls == [topic]
    assert len(state.memory.unrecovered_topics) == 1
    assert state.memory.unrecovered_topics[0].topic_id == topic.topic_id
