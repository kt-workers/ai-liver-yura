from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.integrations.streaming import (
    StreamingErrorCode,
)
from subsystems.streaming import build_streaming_subsystem
from subsystems.streaming.adapters.youtube import (
    FakeLiveChatAdapter,
    FakeYouTubePreparationAdapter,
    FakeYouTubeStreamingControlAdapter,
    GoogleYouTubeLiveChatAdapter,
    GoogleYouTubePreparationAdapter,
    GoogleYouTubeStreamingControlAdapter,
    YouTubeApiError,
    YouTubeApiErrorKind,
    build_youtube_adapter_bundle,
    to_streaming_error,
)
from subsystems.streaming.config import (
    YouTubeAdapterMode,
    YouTubeSubsystemConfig,
)

ROOT = Path(__file__).parents[1]
YOUTUBE_ADAPTER = ROOT / "subsystems" / "streaming" / "adapters" / "youtube"
NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_youtube_adapter_has_no_core_or_obs_dependency() -> None:
    forbidden_prefixes = (
        "app.adapters",
        "app.bootstrap",
        "app.plugins",
        "app.runtime",
        "app.services",
        "gui",
        "subsystems.streaming.adapters.obs",
    )
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in YOUTUBE_ADAPTER.rglob("*.py")
        for import_name in _imports(path)
        if any(
            import_name == prefix or import_name.startswith(f"{prefix}.")
            for prefix in forbidden_prefixes
        )
    )

    assert violations == []


def test_core_python_files_do_not_import_google_sdks() -> None:
    sdk_prefixes = (
        "google",
        "google_auth_httplib2",
        "google_auth_oauthlib",
        "googleapiclient",
        "httplib2",
    )
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in (ROOT / "app").rglob("*.py")
        for import_name in _imports(path)
        if any(
            import_name == prefix or import_name.startswith(f"{prefix}.")
            for prefix in sdk_prefixes
        )
    )

    assert violations == []


def test_legacy_youtube_adapter_paths_are_one_way_compatibility_imports() -> None:
    legacy_root = ROOT / "app" / "adapters" / "youtube"
    violations = sorted(
        f"{path.relative_to(ROOT)} -> {import_name}"
        for path in legacy_root.rglob("*.py")
        for import_name in _imports(path)
        if not import_name.startswith("subsystems.streaming.adapters.youtube")
    )
    implementation_classes = sorted(
        f"{path.relative_to(ROOT)}:{node.name}"
        for path in legacy_root.rglob("*.py")
        for node in ast.walk(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )

    assert violations == []
    assert implementation_classes == []


def test_legacy_class_names_resolve_to_subsystem_implementations() -> None:
    from app.adapters.streaming.fake_live_chat_adapter import (
        FakeLiveChatAdapter as LegacyFakeLiveChatAdapter,
    )
    from app.adapters.streaming.fake_streaming_control import (
        FakeYouTubeStreamingControlAdapter as LegacyFakeControl,
    )
    from app.adapters.streaming.fake_youtube_preparation_adapter import (
        FakeYouTubePreparationAdapter as LegacyFakePreparation,
    )
    from app.adapters.youtube.google_youtube_live_chat_adapter import (
        GoogleYouTubeLiveChatAdapter as LegacyLiveChat,
    )
    from app.adapters.youtube.google_youtube_preparation_adapter import (
        GoogleYouTubePreparationAdapter as LegacyPreparation,
    )
    from app.adapters.youtube.google_youtube_streaming_control_adapter import (
        GoogleYouTubeStreamingControlAdapter as LegacyControl,
    )

    assert LegacyFakeLiveChatAdapter is FakeLiveChatAdapter
    assert LegacyFakeControl is FakeYouTubeStreamingControlAdapter
    assert LegacyFakePreparation is FakeYouTubePreparationAdapter
    assert LegacyLiveChat is GoogleYouTubeLiveChatAdapter
    assert LegacyPreparation is GoogleYouTubePreparationAdapter
    assert LegacyControl is GoogleYouTubeStreamingControlAdapter


def test_composition_selects_fake_google_and_disabled_bundles() -> None:
    fake = build_youtube_adapter_bundle(YouTubeSubsystemConfig())
    assert fake.mode is YouTubeAdapterMode.FAKE
    assert isinstance(fake.preparation, FakeYouTubePreparationAdapter)
    assert isinstance(fake.control, FakeYouTubeStreamingControlAdapter)

    google = build_youtube_adapter_bundle(
        YouTubeSubsystemConfig(
            mode=YouTubeAdapterMode.GOOGLE,
            client_secret_path_env="YOUTUBE_CLIENT_SECRET_PATH",
            token_path_env="YOUTUBE_TOKEN_PATH",
        )
    )
    assert google.mode is YouTubeAdapterMode.GOOGLE
    assert isinstance(google.preparation, GoogleYouTubePreparationAdapter)
    assert isinstance(google.control, GoogleYouTubeStreamingControlAdapter)
    assert isinstance(google.live_chat, GoogleYouTubeLiveChatAdapter)

    disabled = build_youtube_adapter_bundle(
        YouTubeSubsystemConfig(mode=YouTubeAdapterMode.DISABLED)
    )
    assert disabled.mode is YouTubeAdapterMode.DISABLED


def test_google_bundle_requires_environment_variable_names() -> None:
    with pytest.raises(ValueError, match="environment variable names"):
        build_youtube_adapter_bundle(
            YouTubeSubsystemConfig(mode=YouTubeAdapterMode.GOOGLE)
        )


@pytest.mark.asyncio
async def test_disabled_youtube_is_reported_in_subsystem_health() -> None:
    api = build_streaming_subsystem(
        clock=lambda: NOW,
        youtube_config=YouTubeSubsystemConfig(
            mode=YouTubeAdapterMode.DISABLED,
        ),
    )

    health = await api.get_health()

    assert health.healthy is False
    assert health.components == {
        "runtime": True,
        "obs": True,
        "youtube": False,
        "tts": False,
        "avatar": False,
    }


class _Request:
    def __init__(self, value: object) -> None:
        self._value = value

    def execute(self, num_retries: int) -> object:
        assert num_retries == 0
        return self._value


class _LiveChatClient:
    def __init__(self, value: object) -> None:
        self._value = value

    def liveChatMessages(self) -> _LiveChatClient:  # noqa: N802
        return self

    def list(self, **kwargs: object) -> _Request:
        assert kwargs["part"] == "id,snippet,authorDetails"
        return _Request(self._value)


class _ClientFactory:
    def __init__(self, value: object) -> None:
        self._value = value

    def create(self) -> _LiveChatClient:
        return _LiveChatClient(self._value)


@pytest.mark.asyncio
async def test_live_chat_is_normalized_to_public_comment_without_raw_payload() -> None:
    raw = {
        "items": [
            {
                "id": "comment-1",
                "snippet": {
                    "type": "textMessageEvent",
                    "publishedAt": "2026-07-31T12:00:00Z",
                    "displayMessage": "hello",
                    "rawSecret": "must-not-cross",
                },
                "authorDetails": {
                    "channelId": "author-1",
                    "displayName": "Viewer",
                    "isChatModerator": True,
                    "profileImageUrl": "must-not-cross",
                },
            }
        ],
        "nextPageToken": "google-page-token",
        "pollingIntervalMillis": 1000,
        "rawSecret": "must-not-cross",
    }
    adapter = GoogleYouTubeLiveChatAdapter(_ClientFactory(raw))

    page = await adapter.list_comments(
        "internal-chat-id",
        None,
        100,
        stream_id="stream-1",
    )

    assert len(page.comments) == 1
    comment = page.comments[0]
    assert comment.comment_id == "comment-1"
    assert comment.author_id == "author-1"
    assert comment.author_display_name == "Viewer"
    assert comment.text == "hello"
    assert comment.stream_id == "stream-1"
    assert comment.moderation_flags == frozenset({"moderator"})
    assert page.cursor is not None
    assert page.cursor.value != "google-page-token"
    assert "must-not-cross" not in repr(comment)
    assert not hasattr(comment, "raw_payload")


def test_youtube_error_maps_to_stable_public_error_without_sdk_exception() -> None:
    public = to_streaming_error(
        YouTubeApiError(
            YouTubeApiErrorKind.NETWORK,
            "YouTube APIへ接続できません。",
            retryable=True,
            api_reason="backendError",
        )
    )

    assert public.code is StreamingErrorCode.EXTERNAL_DEPENDENCY_ERROR
    assert public.retryable is True
    assert public.details == {}
    assert "HttpError" not in repr(public)
