from __future__ import annotations

import pytest

from cloud_validation.character_reference_asr_lab import (
    AnalyzeRequest,
    CharacterReferenceLabService,
    LabSettings,
)
from tools.character_reference_analysis.asr_coordinator import (
    AsrProcessingOutcome,
    AsrProcessingResult,
)
from tools.character_reference_analysis.manifest import (
    AnalysisStepStatus,
    ReferenceAnalysisManifest,
    build_revision_key,
)
from tools.character_reference_analysis.models import (
    ReferenceSource,
    ReferenceSourceKind,
    Transcript,
    TranscriptSegment,
    TranscriptionMetadata,
)


def make_settings() -> LabSettings:
    return LabSettings(
        inbox_folder_id="inbox",
        results_folder_id="results",
        asr_model="gpt-4o-transcribe-diarize",
        username="tester",
        password="secret",
    )


def make_source() -> ReferenceSource:
    return ReferenceSource(
        reference_id="drive:file-1",
        source_kind=ReferenceSourceKind.GOOGLE_DRIVE_VIDEO,
        source_locator="drive-file:file-1",
        display_name="reference.mov",
        content_hash="md5:abc",
        size_bytes=52_790_619,
        duration_seconds=28.44,
        thumbnail_available=True,
    )


class FakeStore:
    def __init__(self, manifest: ReferenceAnalysisManifest | None = None) -> None:
        self.manifest = manifest

    async def has_revision(self, revision_key: str) -> bool:
        return bool(self.manifest and self.manifest.revision_key == revision_key)

    async def load_manifest(
        self, revision_key: str
    ) -> ReferenceAnalysisManifest | None:
        if self.manifest and self.manifest.revision_key == revision_key:
            return self.manifest
        return None

    async def save_manifest(self, manifest: ReferenceAnalysisManifest) -> None:
        self.manifest = manifest

    async def save_transcript(self, transcript: Transcript, *, revision_key: str) -> None:
        del transcript, revision_key


class FakePipeline:
    def __init__(self, source: ReferenceSource) -> None:
        self.source = source
        self.calls: list[tuple[str, bool]] = []
        self.thumbnail_calls = 0

    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        return (self.source,)

    async def fetch_thumbnail(
        self,
        source: ReferenceSource,
    ) -> tuple[bytes, str] | None:
        assert source == self.source
        self.thumbnail_calls += 1
        return b"thumbnail", "image/jpeg"

    async def process_source(
        self,
        source: ReferenceSource,
        *,
        language: str | None = "ja",
        retry: bool = False,
    ) -> AsrProcessingResult:
        self.calls.append((language or "", retry))
        transcript = Transcript(
            reference_id=source.reference_id,
            text="参考用の文字起こしです。",
            segments=(
                TranscriptSegment(
                    text="参考用の文字起こしです。",
                    start_seconds=0.0,
                    end_seconds=1.0,
                    language="ja",
                    speaker="A",
                ),
            ),
            metadata=TranscriptionMetadata(
                provider="fake",
                model="fake",
                requested_language="ja",
                detected_language="ja",
                response_format="diarized_json",
            ),
        )
        return AsrProcessingResult(
            outcome=AsrProcessingOutcome.COMPLETED,
            revision_key=build_revision_key(source),
            transcript=transcript,
        )


@pytest.mark.asyncio
async def test_lab_list_does_not_expose_private_source_locator() -> None:
    source = make_source()
    manifest = ReferenceAnalysisManifest.for_source(source).with_asr_status(
        AnalysisStepStatus.COMPLETED
    )
    service = CharacterReferenceLabService(
        make_settings(),
        pipeline=FakePipeline(source),
        store=FakeStore(manifest),
    )

    items = await service.list_references()

    assert len(items) == 1
    assert items[0]["reference_id"] == "drive:file-1"
    assert items[0]["asr_status"] == "completed"
    assert items[0]["size_bytes"] == 52_790_619
    assert items[0]["duration_seconds"] == pytest.approx(28.44)
    assert items[0]["drive_thumbnail_available"] is True
    assert items[0]["preview_available"] is True
    assert items[0]["reference_only"] is True
    assert "source_locator" not in items[0]


@pytest.mark.asyncio
async def test_lab_thumbnail_is_proxied_from_pipeline() -> None:
    source = make_source()
    pipeline = FakePipeline(source)
    service = CharacterReferenceLabService(
        make_settings(),
        pipeline=pipeline,
        store=FakeStore(),
    )

    await service.list_references()
    thumbnail = await service.thumbnail(source.reference_id)

    assert thumbnail == (b"thumbnail", "image/jpeg")
    assert pipeline.thumbnail_calls == 1


@pytest.mark.asyncio
async def test_lab_analysis_forces_japanese_and_returns_only_preview() -> None:
    source = make_source()
    pipeline = FakePipeline(source)
    service = CharacterReferenceLabService(
        make_settings(),
        pipeline=pipeline,
        store=FakeStore(),
    )

    result = await service.analyze(AnalyzeRequest(reference_id=source.reference_id))

    assert result["outcome"] == "completed"
    assert result["segment_count"] == 1
    assert result["reference_only"] is True
    assert result["transcript_preview"] == "参考用の文字起こしです。"
    assert pipeline.calls == [("ja", False)]


@pytest.mark.asyncio
async def test_lab_rejects_unknown_reference_id() -> None:
    source = make_source()
    service = CharacterReferenceLabService(
        make_settings(),
        pipeline=FakePipeline(source),
        store=FakeStore(),
    )

    with pytest.raises(ValueError, match="reference_id"):
        await service.analyze(AnalyzeRequest(reference_id="drive:missing"))


def test_lab_settings_use_same_folder_when_results_folder_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YURA_REFERENCE_DRIVE_INBOX_FOLDER_ID", "folder-1")
    monkeypatch.delenv("YURA_REFERENCE_DRIVE_RESULTS_FOLDER_ID", raising=False)
    monkeypatch.setenv("YURA_REFERENCE_LAB_USERNAME", "u")
    monkeypatch.setenv("YURA_REFERENCE_LAB_PASSWORD", "p")

    settings = LabSettings.from_env()

    assert settings.inbox_folder_id == "folder-1"
    assert settings.results_folder_id == "folder-1"
    assert settings.auth_configured is True
