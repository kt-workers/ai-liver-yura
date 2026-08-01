"""Streaming-owned Session, Run of Show, and Comment application graph."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.integrations.streaming import StreamingEventEnvelope
from subsystems.streaming.application.comment_moderation import (
    CommentModerationUsecase,
)
from subsystems.streaming.application.comment_ranking import CommentRankingUsecase
from subsystems.streaming.application.comment_response import CommentResponseUsecase
from subsystems.streaming.application.end_session import EndStreamSessionUsecase
from subsystems.streaming.application.lifecycle_gate import StreamLifecycleGate
from subsystems.streaming.application.live_chat_poller import YouTubeLiveChatPoller
from subsystems.streaming.application.main_segment import StreamMainSegmentUsecase
from subsystems.streaming.application.opening import StreamOpeningUsecase
from subsystems.streaming.application.prepare_session import (
    PrepareStreamSessionUsecase,
)
from subsystems.streaming.application.start_session import StartStreamSessionUsecase
from subsystems.streaming.ports.comment_events import StreamingCommentIngressEvent
from subsystems.streaming.ports.streaming_preparation import StreamSessionRepository

CommentEventSink = Callable[[StreamingCommentIngressEvent], Awaitable[None]]
PollerFactory = Callable[[str, CommentEventSink], YouTubeLiveChatPoller]


@dataclass(frozen=True, slots=True)
class StreamingSessionComponents:
    """Canonical application surface owned by the Streaming Subsystem."""

    sessions: StreamSessionRepository
    prepare: PrepareStreamSessionUsecase
    start: StartStreamSessionUsecase
    end: EndStreamSessionUsecase
    lifecycle: StreamLifecycleGate
    opening: StreamOpeningUsecase
    main_segment: StreamMainSegmentUsecase
    moderation: CommentModerationUsecase
    ranking: CommentRankingUsecase
    response: CommentResponseUsecase
    create_comment_poller: PollerFactory
    public_comment_events: list[StreamingEventEnvelope]
    core_comment_decision: object | None = None
