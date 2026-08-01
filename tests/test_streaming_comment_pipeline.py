import pytest

from subsystems.streaming.bootstrap import build_streaming_subsystem
from subsystems.streaming.domain import StreamSession, StreamSessionStatus
from subsystems.streaming.ports.comment_events import StreamingCommentIngressEvent


def _make_live(api: object) -> StreamSession:
    repository = api.sessions.sessions
    session = repository.create(StreamSession("trace", "broadcast", "title"))
    for status in (
        StreamSessionStatus.PREPARING,
        StreamSessionStatus.READY,
        StreamSessionStatus.START_APPROVED,
        StreamSessionStatus.STARTING,
        StreamSessionStatus.LIVE,
    ):
        session = repository.save(session.transition(status))
    return session


@pytest.mark.asyncio
async def test_normalized_comment_flows_to_moderation_and_ranking_pool() -> None:
    api = build_streaming_subsystem()
    session = _make_live(api)
    api.sessions.lifecycle.update_external_state(
        session.session_id,
        {
            "obs_output": "active",
            "youtube_stream": "active",
            "youtube_broadcast": "live",
            "stream_session": "live",
        },
    )
    event = StreamingCommentIngressEvent(
        "youtube_comment",
        {
            "session_id": session.session_id,
            "message_id": "message-1",
            "comment": "今日の配信は楽しい？",
            "message_type": "text",
            "author": {"channel_id": "author-1", "display_name": "viewer"},
            "published_at": session.updated_at.isoformat(),
        },
    )
    decision = await api.sessions.moderation.evaluate_event(event)
    assert decision is not None
    assert decision.status == "allow"
    assert api.sessions.ranking.status(session.session_id).pool_size == 1


@pytest.mark.asyncio
async def test_comment_is_rejected_by_lifecycle_before_live() -> None:
    api = build_streaming_subsystem()
    session = api.sessions.sessions.create(StreamSession("trace", "broadcast", "title"))
    result = await api.sessions.moderation.evaluate_event(
        StreamingCommentIngressEvent(
            "youtube_comment",
            {"session_id": session.session_id, "message_id": "m", "comment": "hello"},
        )
    )
    assert result is None
