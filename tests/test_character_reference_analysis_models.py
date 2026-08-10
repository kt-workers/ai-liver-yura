from __future__ import annotations

import pytest

from tools.character_reference_analysis.models import (
    ObservationAbstractionLevel,
    ObservationAdoptionStatus,
    ReferenceObservation,
    ReferenceSource,
    ReferenceSourceKind,
    ReferenceUsagePolicy,
    Transcript,
    TranscriptSegment,
    TranscriptionMetadata,
    YuraDesignCandidate,
)


def test_reference_usage_policy_is_reference_only() -> None:
    policy = ReferenceUsagePolicy()

    assert policy.source_usage == "reference_only"
    assert policy.verbatim_reuse_allowed is False
    assert policy.voice_clone_allowed is False
    assert policy.motion_copy_allowed is False
    assert policy.asset_reuse_allowed is False
    assert policy.character_setting_auto_adoption is False


def test_reference_usage_policy_rejects_reuse_enablement() -> None:
    with pytest.raises(ValueError, match="reuse must remain disabled"):
        ReferenceUsagePolicy(voice_clone_allowed=True)


def test_reference_source_serializes_usage_boundary() -> None:
    source = ReferenceSource(
        reference_id="drive:example",
        source_kind=ReferenceSourceKind.GOOGLE_DRIVE_VIDEO,
        source_locator="https://drive.google.com/file/d/example/view",
        display_name="reference.mov",
    )

    value = source.to_dict()

    assert value["source_kind"] == "google_drive_video"
    assert value["analysis_status"] == "pending"
    assert value["usage_policy"]["source_usage"] == "reference_only"
    assert value["usage_policy"]["motion_copy_allowed"] is False


def test_transcript_reports_timestamp_coverage() -> None:
    transcript = Transcript(
        reference_id="ref-001",
        text="こんにちは。今日はよろしくね。",
        segments=(
            TranscriptSegment(
                text="こんにちは。",
                start_seconds=0.0,
                end_seconds=1.2,
                language="ja",
                speaker="A",
            ),
            TranscriptSegment(
                text="今日はよろしくね。",
                start_seconds=1.2,
                end_seconds=2.8,
                language="ja",
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


def test_reference_observation_contains_only_abstract_evidence_link() -> None:
    observation = ReferenceObservation(
        observation_id="obs-001",
        reference_id="drive:example",
        category="interaction_style",
        observation="関心が高まった時に発話テンポと反応量が増える",
        evidence_refs=("drive:example#12.4-18.1",),
        abstraction_level=ObservationAbstractionLevel.BEHAVIORAL_PATTERN,
    )

    value = observation.to_dict()

    assert value["adoption_status"] == "unreviewed"
    assert "raw_media" not in value
    assert "raw_transcript" not in value
    assert "motion_sequence" not in value


def test_yura_candidate_requires_explicit_observation_derivation() -> None:
    candidate = YuraDesignCandidate(
        candidate_id="candidate-001",
        derived_from_observations=("obs-001", "obs-002"),
        yura_specific_design=(
            "普段は柔らかく落ち着き、好奇心が高まると自然に反応量が増える"
        ),
        status=ObservationAdoptionStatus.CANDIDATE,
    )

    assert candidate.to_dict()["status"] == "candidate"
    assert candidate.derived_from_observations == ("obs-001", "obs-002")
