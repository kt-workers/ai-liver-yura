from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_state import AgentState
from app.runtime.runtime_diagnostic_snapshot_builder import (
    RuntimeDiagnosticSnapshotBuilder,
)


def test_build_returns_stable_empty_runtime_snapshot() -> None:
    snapshot = RuntimeDiagnosticSnapshotBuilder().build(
        state=AgentState(),
        activity_manager=ActivityManager(),
        plugin_manager=None,
    )

    assert set(snapshot) == {
        "emotion",
        "drive",
        "relationship",
        "relationship_count",
        "memory",
        "situation",
        "activity",
        "plugins",
        "stream_status",
    }
    assert snapshot["relationship"] == {"present": False}
    assert snapshot["relationship_count"] == 0
    assert snapshot["memory"] == {
        "episodic_count": 0,
        "semantic_count": 0,
        "unfinished_activity_count": 0,
        "unrecovered_topic_count": 0,
        "emotion_history_count": 0,
    }
    assert snapshot["activity"] == {
        "foreground_id": None,
        "foreground_type": None,
        "foreground_status": None,
        "pending_count": 0,
        "suspended_count": 0,
        "ongoing_id": None,
        "ongoing_type": None,
        "ongoing_status": None,
    }
    assert snapshot["plugins"] == {
        "statuses": {},
        "available_capabilities": [],
    }


def test_build_does_not_include_conversation_text_or_secret_fields() -> None:
    snapshot = RuntimeDiagnosticSnapshotBuilder().build(
        state=AgentState(),
        activity_manager=ActivityManager(),
        plugin_manager=None,
    )

    serialized = repr(snapshot).lower()
    assert "conversation" not in serialized
    assert "api_key" not in serialized
    assert "password" not in serialized
    assert "token" not in serialized
