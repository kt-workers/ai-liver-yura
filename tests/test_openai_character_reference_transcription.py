from __future__ import annotations

from pathlib import Path

from tools.character_reference_analysis.openai_transcription import (
    OpenAITranscriptionBackend,
)


def test_diarize_model_uses_timestamped_speaker_format() -> None:
    backend = OpenAITranscriptionBackend(model="gpt-4o-transcribe-diarize")

    response_format, fields = backend._request_fields("ja")

    assert response_format == "diarized_json"
    assert ("language", "ja") in fields
    assert ("response_format", "diarized_json") in fields
    assert ("chunking_strategy", "auto") in fields


def test_whisper_model_requests_segment_timestamps() -> None:
    backend = OpenAITranscriptionBackend(model="whisper-1")

    response_format, fields = backend._request_fields("ja")

    assert response_format == "verbose_json"
    assert ("timestamp_granularities[]", "segment") in fields


def test_gpt4o_transcribe_uses_json_without_fake_timestamps() -> None:
    backend = OpenAITranscriptionBackend(model="gpt-4o-transcribe")

    response_format, fields = backend._request_fields("ja")
    transcript = backend._parse_response(
        {"text": "ゆっくり話すね。"},
        reference_id="ref-simple",
        requested_language="ja",
        response_format=response_format,
    )

    assert response_format == "json"
    assert ("response_format", "json") in fields
    assert transcript.text == "ゆっくり話すね。"
    assert transcript.segments == ()
    assert transcript.has_timestamps is False


def test_diarized_json_is_normalized_to_common_segments() -> None:
    backend = OpenAITranscriptionBackend(model="gpt-4o-transcribe-diarize")

    transcript = backend._parse_response(
        {
            "duration": 4.5,
            "text": "こんにちは。気になるね。",
            "segments": [
                {
                    "id": "seg_001",
                    "start": 0.0,
                    "end": 1.5,
                    "text": "こんにちは。",
                    "speaker": "A",
                },
                {
                    "id": "seg_002",
                    "start": 1.5,
                    "end": 4.5,
                    "text": "気になるね。",
                    "speaker": "A",
                },
            ],
        },
        reference_id="ref-diarized",
        requested_language="ja",
        response_format="diarized_json",
    )

    assert transcript.reference_id == "ref-diarized"
    assert transcript.has_timestamps is True
    assert transcript.metadata.model == "gpt-4o-transcribe-diarize"
    assert transcript.metadata.source_duration_seconds == 4.5
    assert [segment.speaker for segment in transcript.segments] == ["A", "A"]
    assert [segment.language for segment in transcript.segments] == ["ja", "ja"]


def test_verbose_json_is_normalized_without_copying_provider_specific_fields() -> None:
    backend = OpenAITranscriptionBackend(model="whisper-1")

    transcript = backend._parse_response(
        {
            "language": "japanese",
            "duration": 3.0,
            "text": "今日は楽しいね。",
            "segments": [
                {
                    "id": 0,
                    "seek": 0,
                    "start": 0.1,
                    "end": 2.9,
                    "text": " 今日は楽しいね。",
                    "tokens": [1, 2, 3],
                    "avg_logprob": -0.2,
                }
            ],
        },
        reference_id="ref-whisper",
        requested_language="ja",
        response_format="verbose_json",
    )

    assert transcript.metadata.detected_language == "japanese"
    assert transcript.segments[0].text == "今日は楽しいね。"
    assert transcript.segments[0].language == "ja"
    assert transcript.segments[0].asr_confidence is None


def test_multipart_contains_language_model_and_media(tmp_path: Path) -> None:
    media = tmp_path / "sample.mov"
    media.write_bytes(b"reference-media")
    backend = OpenAITranscriptionBackend(model="gpt-4o-transcribe-diarize")
    _, fields = backend._request_fields("ja")

    body, content_type = backend._build_multipart(media, fields)

    assert content_type.startswith("multipart/form-data; boundary=")
    assert b"gpt-4o-transcribe-diarize" in body
    assert b'name="language"' in body
    assert b"ja" in body
    assert b'name="file"' in body
    assert b"reference-media" in body
