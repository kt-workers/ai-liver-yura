from __future__ import annotations

import pytest

from tools.character_reference_analysis.models import (
    ReferenceSource,
    ReferenceSourceKind,
    ReferenceUsagePolicy,
    Transcript,
    TranscriptSegment,
    TranscriptionMetadata,
)


def test_reference_usage_policy_is_reference_only() -> None:
    policy = ReferenceUsagePolicy()

    assert policy.purpose == "reference_only"
    assert policy.allow_original_media_reuse is False
    assert policy.allow_voice_reuse is False
    assert policy.allow_utterance_reuse is False
    assert policy.allow_motion_reuse is False
    assert policy.allow_character_setting_copy is False


def test_reference_usage_policy_rejects_reuse_enablement() -> None:
    with pytest.raises(ValueError, match="reuse must remain disabled"):
        ReferenceUsagePolicy(allow_voice_reuse=True)


def test_reference_source_serializes_usage_boundary() -> None:
    source = ReferenceSource(
        reference_id="ref-001",
        source_kind=ReferenceSourceKind.GOOGLE_DRIVE,
        source_uri="https://drive.google.com/file/d/example/view",
        display_name="reference.mov",
    )

    value = source.to_dict()

    assert value["source_kind"] == "google_drive"
    assert value["usage_policy"]["purpose"] == "reference_only"
    assert value["usage_policy"]["allow_motion_reuse"] is False


def test_transcript_reports_timestamp_coverage() -> None:
    transcript = Transcript(
        reference_id="ref-001",
        text="こんにちは。今日はよろしくね。",
        segments=(
            TranscriptSegment(
                text="こんにちは。",
                start_seconds=0.0,
                end_seconds=1.2,
                speaker="A",
            ),
            TranscriptSegment(
                text="今日はよろしくね。",
                start_seconds=1.2,
                end_seconds=2.8,
                speaker="A",
            ),
        ),
        metadata=TranscriptionMetadata(
            provider="openai",
            model="gpt-4o-transcribe-diarize",
            requested_language="ja",
            detected_language=None,
            response_format="diarized_json",
            source_duration_seconds=2.8,
        ),
    )

    assert transcript.has_timestamps is True
    assert transcript.to_dict()["segments"][0]["speaker"] == "A"


def test_transcript_segment_rejects_invalid_time_range() -> None:
    with pytest.raises(ValueError, match="end_seconds"):
        TranscriptSegment(text="test", start_seconds=2.0, end_seconds=1.0)
