from app.adapters.streaming.fake_comment_moderation_adapter import (
    FakeCommentModerationAdapter,
)
from app.adapters.streaming.health_adapters import (
    FakeAvatarHealthAdapter,
    FakeTtsHealthAdapter,
    UnavailableAvatarHealthAdapter,
    VoiceVoxHealthAdapter,
    VoiceVoxHealthConfig,
)
from app.adapters.streaming.in_memory_comment_moderation_repository import (
    InMemoryCommentModerationRepository,
)
from app.adapters.streaming.in_memory_comment_ranking_repositories import (
    InMemoryCommentCandidateRepository,
    InMemoryCommentRankingRepository,
    InMemoryCommentResponseHistoryRepository,
    InMemoryCommentSelectionRepository,
)
from app.adapters.streaming.in_memory_comment_response_repositories import (
    InMemoryCommentResponseActivityRepository,
    InMemoryCommentResponseHistory,
)
from app.adapters.streaming.in_memory_main_segment_repository import (
    InMemoryStreamMainSegmentRepository,
)
from app.adapters.streaming.in_memory_opening_repository import (
    InMemoryStreamOpeningRepository,
)
from app.adapters.streaming.in_memory_session_repository import (
    InMemoryStreamSessionRepository,
)
from app.adapters.streaming.preparation_publisher import (
    InMemoryStreamPreparationPublisher,
)
from app.adapters.streaming.yaml_run_of_show_repository import YamlRunOfShowRepository

__all__ = [
    "DisabledObsPreparationAdapter",
    "FakeAvatarHealthAdapter",
    "FakeTtsHealthAdapter",
    "FakeObsPreparationAdapter",
    "FakeLiveChatAdapter",
    "FakeCommentModerationAdapter",
    "InMemoryCommentModerationRepository",
    "InMemoryCommentCandidateRepository",
    "InMemoryCommentRankingRepository",
    "InMemoryCommentResponseHistoryRepository",
    "InMemoryCommentSelectionRepository",
    "InMemoryCommentResponseActivityRepository",
    "InMemoryCommentResponseHistory",
    "FakeObsPreparationConfig",
    "FakeYouTubePreparationAdapter",
    "FakeYouTubePreparationConfig",
    "InMemoryStreamPreparationPublisher",
    "InMemoryStreamOpeningRepository",
    "InMemoryStreamMainSegmentRepository",
    "InMemoryStreamSessionRepository",
    "ObsWebSocketPreparationAdapter",
    "UnavailableAvatarHealthAdapter",
    "UnavailableYouTubePreparationAdapter",
    "VoiceVoxHealthAdapter",
    "VoiceVoxHealthConfig",
    "YamlRunOfShowRepository",
]

_YOUTUBE_COMPAT_EXPORTS = frozenset(
    {
        "FakeLiveChatAdapter",
        "FakeYouTubePreparationAdapter",
        "FakeYouTubePreparationConfig",
        "UnavailableYouTubePreparationAdapter",
    }
)
_OBS_COMPAT_EXPORTS = frozenset(
    {
        "DisabledObsPreparationAdapter",
        "FakeObsPreparationAdapter",
        "FakeObsPreparationConfig",
        "ObsWebSocketPreparationAdapter",
    }
)


def __getattr__(name: str) -> object:
    if name in _OBS_COMPAT_EXPORTS:
        module_name = "subsystems.streaming.adapters.obs"
    elif name in _YOUTUBE_COMPAT_EXPORTS:
        module_name = "subsystems.streaming.adapters.youtube.fake_youtube"
    else:
        raise AttributeError(name)
    module = __import__(module_name, fromlist=[name])
    return getattr(module, name)
