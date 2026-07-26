from __future__ import annotations

from dataclasses import asdict

from app.core.plugins import PluginManager
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_state import AgentState


class RuntimeDiagnosticSnapshotBuilder:
    """Coreの状態から、秘密情報や会話本文を含まない診断Snapshotを生成する。"""

    def build(
        self,
        *,
        state: AgentState,
        activity_manager: ActivityManager,
        plugin_manager: PluginManager | None,
    ) -> dict[str, object]:
        foreground = activity_manager.foreground_activity
        ongoing = activity_manager.ongoing_activity
        relationship = state.relationship_memory.current
        plugin_statuses: dict[str, str] = {}
        if plugin_manager is not None:
            for plugin in plugin_manager.list_plugins():
                status = plugin_manager.status(plugin.plugin_id)
                plugin_statuses[plugin.plugin_id] = (
                    status.value if status is not None else "unknown"
                )

        return {
            "emotion": asdict(state.current_emotion),
            "drive": asdict(state.current_drive),
            "relationship": (
                {
                    "present": True,
                    "role": relationship.role,
                    "familiarity": relationship.familiarity,
                    "trust": relationship.trust,
                    "affinity": relationship.affinity,
                    "interaction_count": relationship.interaction_count,
                }
                if relationship is not None
                else {"present": False}
            ),
            "relationship_count": len(state.relationship_memory.relationships),
            "memory": {
                "episodic_count": len(state.memory.episodic),
                "semantic_count": len(state.memory.semantic),
                "unfinished_activity_count": len(state.memory.unfinished_activities),
                "unrecovered_topic_count": len(state.memory.unrecovered_topics),
                "emotion_history_count": len(state.memory.emotion_history),
            },
            "situation": {
                "last_event_type": state.current_situation.last_event_type,
                "last_event_at": (
                    state.current_situation.last_event_at.isoformat()
                    if state.current_situation.last_event_at is not None
                    else None
                ),
                "input_source": state.current_situation.input_source,
                "active_activity_type": state.current_situation.active_activity_type,
                "pending_activity_count": state.current_situation.pending_activity_count,
                "suspended_activity_count": state.current_situation.suspended_activity_count,
                "ongoing_activity_type": state.current_situation.ongoing_activity_type,
                "ongoing_activity_status": state.current_situation.ongoing_activity_status,
            },
            "activity": {
                "foreground_id": (
                    foreground.activity_id if foreground is not None else None
                ),
                "foreground_type": (
                    foreground.activity_type.value if foreground is not None else None
                ),
                "foreground_status": (
                    foreground.status.value if foreground is not None else None
                ),
                "pending_count": len(activity_manager.pending_activities()),
                "suspended_count": len(activity_manager.suspended_activities()),
                "ongoing_id": (
                    ongoing.ongoing_activity_id if ongoing is not None else None
                ),
                "ongoing_type": ongoing.activity_type if ongoing is not None else None,
                "ongoing_status": ongoing.status.value if ongoing is not None else None,
            },
            "plugins": (
                {
                    "statuses": plugin_statuses,
                    "available_capabilities": sorted(
                        plugin_manager.list_capabilities()
                    ),
                }
                if plugin_manager is not None
                else {"statuses": {}, "available_capabilities": []}
            ),
            "stream_status": state.stream_status,
        }
