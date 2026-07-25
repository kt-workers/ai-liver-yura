from __future__ import annotations

from app.domain.memory import UnfinishedActivityMemory, UnrecoveredTopicMemory
from app.domain.topic import InterruptedTopic, TopicLifecycleStatus
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_state import AgentState


class ActivityStateSynchronizer:
    """ActivityManagerの現在状態をAgentStateへ反映する。"""

    def __init__(self, activity_manager: ActivityManager) -> None:
        self._activity_manager = activity_manager

    def synchronize(
        self,
        state: AgentState,
        *,
        autonomous_topic: InterruptedTopic | None = None,
    ) -> AgentState:
        pending = self._activity_manager.pending_activities()
        suspended = self._activity_manager.suspended_activities()
        foreground = self._activity_manager.foreground_activity
        ongoing = self._activity_manager.ongoing_activity

        unfinished = tuple(
            UnfinishedActivityMemory(
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                goal=activity.goal,
                status=activity.status.value,
                priority=activity.priority,
                updated_at=activity.updated_at,
            )
            for activity in self._activity_manager.list_activities()
            if activity.status.value in {"pending", "active", "waiting", "suspended"}
        )
        unrecovered_topic = self._build_unrecovered_topic(autonomous_topic)

        return (
            state.with_active_activity(foreground)
            .with_pending_activities(pending)
            .with_suspended_activities(suspended)
            .with_memory(
                state.memory.with_unfinished_activities(unfinished).with_unrecovered_topic(
                    unrecovered_topic
                )
            )
            .with_situation(
                state.current_situation.with_activity_snapshot(
                    active_activity_id=(
                        foreground.activity_id if foreground is not None else None
                    ),
                    active_activity_type=(
                        foreground.activity_type.value if foreground is not None else None
                    ),
                    pending_activity_count=len(pending),
                    suspended_activity_count=len(suspended),
                    ongoing_activity_id=(
                        ongoing.ongoing_activity_id if ongoing is not None else None
                    ),
                    ongoing_activity_type=(
                        ongoing.activity_type if ongoing is not None else None
                    ),
                    ongoing_activity_status=(
                        ongoing.status.value if ongoing is not None else None
                    ),
                )
            )
        )

    @staticmethod
    def _build_unrecovered_topic(
        topic: InterruptedTopic | None,
    ) -> UnrecoveredTopicMemory | None:
        if topic is None or topic.status not in {
            TopicLifecycleStatus.INTERRUPTED,
            TopicLifecycleStatus.SUSPENDED,
        }:
            return None
        return UnrecoveredTopicMemory(
            topic_id=topic.topic_id,
            source_activity_id=topic.source_activity_id,
            summary=topic.original_text,
            status=topic.status.value,
            importance=topic.importance,
            interrupted_at=topic.interrupted_at,
        )
