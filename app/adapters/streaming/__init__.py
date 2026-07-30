from importlib import import_module

from app.adapters.obs import ObsWebSocketPreparationAdapter
from app.adapters.streaming.fake_comment_moderation_adapter import (
    FakeCommentModerationAdapter,
)
from app.adapters.streaming.fake_obs_preparation_adapter import (
    DisabledObsPreparationAdapter,
    FakeObsPreparationAdapter,
    FakeObsPreparationConfig,
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


def __getattr__(name: str) -> object:
    if name not in _YOUTUBE_COMPAT_EXPORTS:
        raise AttributeError(name)
    module = import_module(
        "subsystems.streaming.adapters.youtube.fake_youtube"
    )
    return getattr(module, name)
