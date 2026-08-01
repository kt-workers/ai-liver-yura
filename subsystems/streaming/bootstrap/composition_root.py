"""Build the Core-independent Streaming Subsystem object graph."""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

from subsystems.streaming.adapters import FakeStreamingRuntime
from subsystems.streaming.adapters.dependency_health import (
    CompositeDependencyHealthProvider,
)
from subsystems.streaming.adapters.obs import build_obs_adapter_bundle
from subsystems.streaming.adapters.preparation_health import (
    StaticPreparationHealthAdapter,
)
from subsystems.streaming.adapters.repositories.in_memory_comment_moderation_repository import (
    InMemoryCommentModerationRepository,
)
from subsystems.streaming.adapters.repositories.in_memory_comment_ranking_repositories import (
    InMemoryCommentCandidateRepository,
    InMemoryCommentRankingRepository,
    InMemoryCommentResponseHistoryRepository,
    InMemoryCommentSelectionRepository,
)
from subsystems.streaming.adapters.repositories.in_memory_comment_response_repositories import (
    InMemoryCommentResponseActivityRepository,
    InMemoryCommentResponseHistory,
)
from subsystems.streaming.adapters.repositories.in_memory_main_segment_repository import (
    InMemoryStreamMainSegmentRepository,
)
from subsystems.streaming.adapters.repositories.in_memory_opening_repository import (
    InMemoryStreamOpeningRepository,
)
from subsystems.streaming.adapters.repositories.in_memory_run_of_show_repository import (
    InMemoryRunOfShowRepository,
)
from subsystems.streaming.adapters.repositories.in_memory_session_repository import (
    InMemoryStreamSessionRepository,
)
from subsystems.streaming.adapters.repositories.preparation_publisher import (
    InMemoryStreamPreparationPublisher,
)
from subsystems.streaming.adapters.youtube import build_youtube_adapter_bundle
from subsystems.streaming.api import StreamingSubsystemApi
from subsystems.streaming.application import (
    CommentModerationUsecase,
    CommentRankingUsecase,
    CommentResponseUsecase,
    DependencyHealthProvider,
    DependencyHealthService,
    EndStreamSessionUsecase,
    PrepareStreamSessionUsecase,
    StartStreamSessionUsecase,
    StreamingSessionComponents,
    StreamingSubsystemService,
    StreamLifecycleGate,
    StreamMainSegmentUsecase,
    StreamOpeningUsecase,
    StreamPreparationRequirements,
    YouTubeLiveChatPoller,
)
from subsystems.streaming.application.settings import (
    DefaultCommentModerationSettings,
    DefaultCommentRankingSettings,
    DefaultCommentResponseSettings,
)
from subsystems.streaming.config import (
    EnvironmentSecretProvider,
    ObsSubsystemConfig,
    SecretProvider,
    StreamingSubsystemConfig,
    YouTubeSubsystemConfig,
    validate_streaming_subsystem_config,
)
from subsystems.streaming.domain import RunOfShowSegment, RunOfShowSummary
from subsystems.streaming.ports.comment_events import StreamingCommentIngressEvent
from subsystems.streaming.ports.content_execution import (
    StreamContentExecutionResult,
    UnavailableStreamContentExecutor,
)

ContentExecutor = Callable[[dict[str, object], str], Awaitable[StreamContentExecutionResult]]


def build_streaming_subsystem(
    *,
    clock: Callable[[], datetime] | None = None,
    config: StreamingSubsystemConfig | None = None,
    secret_provider: SecretProvider | None = None,
    dependency_health_providers: Sequence[DependencyHealthProvider] = (),
    obs_config: ObsSubsystemConfig | None = None,
    youtube_config: YouTubeSubsystemConfig | None = None,
    content_executor: ContentExecutor | None = None,
    core_comment_decision: object | None = None,
) -> StreamingSubsystemApi:
    """Build from Subsystem-owned config and externally supplied secrets."""

    if config is not None and (obs_config is not None or youtube_config is not None):
        raise ValueError("config cannot be combined with legacy adapter configs")
    subsystem_config = config or StreamingSubsystemConfig(
        youtube=youtube_config or YouTubeSubsystemConfig(),
        obs=obs_config or ObsSubsystemConfig(),
    )
    secrets = secret_provider or EnvironmentSecretProvider()
    validate_streaming_subsystem_config(subsystem_config, secrets)
    obs = build_obs_adapter_bundle(subsystem_config.obs, secrets)
    youtube = build_youtube_adapter_bundle(
        subsystem_config.youtube,
        secrets,
    )
    health_catalog = (
        CompositeDependencyHealthProvider(dependency_health_providers)
        if clock is None
        else CompositeDependencyHealthProvider(
            dependency_health_providers,
            clock=clock,
        )
    )
    health_service = DependencyHealthService(health_catalog)
    runtime = (
        FakeStreamingRuntime(
            dependency_health=health_service,
            obs=obs,
            youtube=youtube,
        )
        if clock is None
        else FakeStreamingRuntime(
            clock=clock,
            dependency_health=health_service,
            obs=obs,
            youtube=youtube,
        )
    )
    service = StreamingSubsystemService(runtime)
    session_components = _build_session_components(
        obs=obs,
        youtube=youtube,
        content_executor=content_executor or UnavailableStreamContentExecutor(),
        content_execution_connected=content_executor is not None,
        core_comment_decision=core_comment_decision,
        required_audio_sources=subsystem_config.obs.required_audio_sources,
    )
    return StreamingSubsystemApi(service, sessions=session_components)


def _default_run_of_show() -> InMemoryRunOfShowRepository:
    segments = (
        RunOfShowSegment("opening", "opening", "Opening", 60, True, "prompt", "opening", 0),
        RunOfShowSegment("main", "main", "Main", 1800, True, "prompt", "main", 1),
        RunOfShowSegment("closing", "closing", "Closing", 60, True, "prompt", "closing", 2),
    )
    summary = RunOfShowSummary("default", "Default", 1920, len(segments), "subsystem:default", "1")
    return InMemoryRunOfShowRepository(((summary, segments),))


def _build_session_components(
    *,
    obs: object,
    youtube: object,
    content_executor: ContentExecutor,
    content_execution_connected: bool,
    core_comment_decision: object | None,
    required_audio_sources: tuple[str, ...],
) -> StreamingSessionComponents:
    sessions = InMemoryStreamSessionRepository()
    openings = InMemoryStreamOpeningRepository()
    main_segments = InMemoryStreamMainSegmentRepository()
    run_of_show = _default_run_of_show()
    lifecycle = StreamLifecycleGate(
        sessions=sessions,
        openings=openings,
        main_segments=main_segments,
    )
    prepare = PrepareStreamSessionUsecase(
        youtube=youtube.preparation,
        obs=obs.preparation,
        tts=StaticPreparationHealthAdapter("tts"),
        avatar=StaticPreparationHealthAdapter("avatar"),
        run_of_show=run_of_show,
        sessions=sessions,
        publisher=InMemoryStreamPreparationPublisher(),
        requirements=StreamPreparationRequirements(
            require_tts=False,
            require_avatar=False,
            required_audio_sources=required_audio_sources,
        ),
    )
    start = StartStreamSessionUsecase(
        sessions=sessions,
        obs=obs.control,
        youtube=youtube.control,
        allow_test_adapters=True,
        allow_fake_youtube=True,
        poll_interval_seconds=0,
    )
    opening = StreamOpeningUsecase(
        sessions=sessions,
        openings=openings,
        run_of_show=run_of_show,
        executor=content_executor,
        lifecycle_gate=lifecycle,
    )
    main = StreamMainSegmentUsecase(
        sessions=sessions,
        activities=main_segments,
        run_of_show=run_of_show,
        executor=content_executor,
        lifecycle_gate=lifecycle,
    )
    end = EndStreamSessionUsecase(
        sessions=sessions,
        main_segments=main_segments,
        run_of_show=run_of_show,
        obs=obs.control,
        youtube=youtube.control,
        closing_executor=content_executor,
        output_canceler=lambda: False,
        test_mode=True,
        lifecycle_gate=lifecycle,
    )
    candidates = InMemoryCommentCandidateRepository(capacity=200)
    selections = InMemoryCommentSelectionRepository()
    ranking = CommentRankingUsecase(
        gate=lifecycle,
        candidates=candidates,
        rankings=InMemoryCommentRankingRepository(),
        selections=selections,
        history=InMemoryCommentResponseHistoryRepository(),
        settings=DefaultCommentRankingSettings(),
    )
    moderation = CommentModerationUsecase(
        gate=lifecycle,
        repository=InMemoryCommentModerationRepository(),
        settings=DefaultCommentModerationSettings(),
        candidate_sink=lambda candidate, _trace: ranking.add_candidate(candidate),
    )
    response = CommentResponseUsecase(
        gate=lifecycle,
        activities=InMemoryCommentResponseActivityRepository(),
        selections=ranking,
        history=InMemoryCommentResponseHistory(),
        executor=content_executor,
        settings=DefaultCommentResponseSettings(),
    )
    public_events = []

    async def public_sink(event: object) -> None:
        public_events.append(event)

    def create_poller(
        session_id: str,
        event_sink: Callable[[StreamingCommentIngressEvent], Awaitable[None]],
    ) -> YouTubeLiveChatPoller:
        session = sessions.get(session_id)
        if session is None:
            raise ValueError("stream.session.not_found")
        if not session.live_chat_id:
            raise ValueError("stream.live_chat.not_available")
        return YouTubeLiveChatPoller(
            session_id=session.session_id,
            trace_id=session.trace_id,
            broadcast_id=session.selected_broadcast_id,
            live_chat_id=session.live_chat_id,
            adapter=youtube.live_chat,
            gate=lifecycle,
            event_sink=event_sink,
            public_event_sink=public_sink,
        )

    return StreamingSessionComponents(
        sessions=sessions,
        prepare=prepare,
        start=start,
        end=end,
        lifecycle=lifecycle,
        opening=opening,
        main_segment=main,
        moderation=moderation,
        ranking=ranking,
        response=response,
        create_comment_poller=create_poller,
        public_comment_events=public_events,
        content_execution_connected=content_execution_connected,
        core_comment_decision=core_comment_decision,
    )
