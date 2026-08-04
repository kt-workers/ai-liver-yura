from __future__ import annotations

from app.domain.activities import Activity, ActivityType
from app.runtime.character_response_pipeline import ResponseContextBuilder


def test_user_conversation_projects_event_emotion_and_drive_into_response_context() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={
            "event_payload": {
                "text": "今はどんな気分？",
                "emotion": {
                    "mood": "neutral",
                    "arousal": 0.42,
                    "valence": 0.0,
                },
                "drive": {
                    "curiosity": 0.71,
                    "engagement": 0.64,
                    "energy": 0.55,
                },
            }
        },
    )

    context = ResponseContextBuilder().build(activity)

    assert context.emotion == {
        "mood": "neutral",
        "arousal": 0.42,
        "valence": 0.0,
    }
    assert context.drive == {
        "curiosity": 0.71,
        "engagement": 0.64,
        "energy": 0.55,
    }


def test_event_payload_state_wins_over_older_activity_snapshot() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={
            "event_payload": {
                "text": "どうしたの？",
                "emotion": {"mood": "joyful", "arousal": 0.66},
                "drive": {"curiosity": 0.77, "energy": 0.61},
            },
            "emotion": {"mood": "neutral", "arousal": 0.20},
            "drive": {"curiosity": 0.30, "energy": 0.42},
        },
    )

    context = ResponseContextBuilder().build(activity)

    assert context.emotion == {"mood": "joyful", "arousal": 0.66}
    assert context.drive == {"curiosity": 0.77, "energy": 0.61}


def test_drive_projection_accepts_only_numeric_non_boolean_values() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={
            "event_payload": {
                "text": "元気？",
                "drive": {
                    "curiosity": 1,
                    "energy": 0.58,
                    "enabled": True,
                    "label": "active",
                },
            }
        },
    )

    context = ResponseContextBuilder().build(activity)

    assert context.drive == {"curiosity": 1.0, "energy": 0.58}


def test_autonomous_situation_state_remains_supported() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話す",
        context={
            "autonomous_situation_context": {
                "emotion_state": {
                    "mood": "calm",
                    "arousal": 0.31,
                },
                "drive_state": {
                    "curiosity": 0.82,
                    "energy": 0.73,
                },
            },
            "emotion": {
                "mood": "calm",
                "arousal": 0.31,
            },
        },
    )

    context = ResponseContextBuilder().build(activity)

    assert context.emotion == {
        "mood": "calm",
        "arousal": 0.31,
    }
    assert context.drive == {
        "curiosity": 0.82,
        "energy": 0.73,
    }


def test_activity_context_state_is_used_as_compatibility_fallback() -> None:
    activity = Activity(
        activity_type=ActivityType.STIMULUS_REACTION,
        goal="刺激へ反応する",
        context={
            "event_payload": {"stimulus_kind": "tap"},
            "emotion": {"mood": "surprised", "arousal": 0.79},
            "drive": {"engagement": 0.58, "energy": 0.48},
        },
    )

    context = ResponseContextBuilder().build(activity)

    assert context.emotion == {"mood": "surprised", "arousal": 0.79}
    assert context.drive == {"engagement": 0.58, "energy": 0.48}
