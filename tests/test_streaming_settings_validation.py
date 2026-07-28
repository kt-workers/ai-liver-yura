from __future__ import annotations

import pytest

from app.config.app_config import _load_streaming_settings
from app.config.errors import ConfigError


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("root", "health_timeout_seconds", 0),
        ("moderation", "max_comment_length", 0),
        ("moderation", "repeated_message_window_seconds", 0),
        ("moderation", "repeated_message_limit", 0),
        ("moderation", "max_concurrent_evaluations", 0),
        ("moderation", "evaluation_queue_capacity", 0),
        ("moderation", "timeout_seconds", -1),
        ("comment_ranking", "candidate_ttl_seconds", 0),
        ("comment_ranking", "queue_capacity", 0),
        ("comment_response", "max_characters", 0),
        ("comment_response", "max_retries", -1),
        ("obs", "max_scene_depth", 0),
    ],
)
def test_streaming_ranges_are_validated(
    section: str, key: str, value: object
) -> None:
    raw = {key: value} if section == "root" else {section: {key: value}}
    with pytest.raises(ConfigError, match=key):
        _load_streaming_settings(raw)


@pytest.mark.parametrize("key", ["selection_threshold", "minimum_conversation_fit"])
@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_ranking_confidence_thresholds_are_bounded(key: str, value: float) -> None:
    with pytest.raises((ConfigError, ValueError), match="threshold"):
        _load_streaming_settings({"comment_ranking": {key: value}})


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("moderation", "url_policy", "unknown"),
        ("moderation", "unknown_message_type_policy", "unknown"),
        ("comment_response", "mention_author_name", "always"),
    ],
)
def test_streaming_enum_values_are_strict(
    section: str, key: str, value: str
) -> None:
    with pytest.raises((ConfigError, ValueError), match=key):
        _load_streaming_settings({section: {key: value}})
