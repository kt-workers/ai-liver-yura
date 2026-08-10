from __future__ import annotations

from pathlib import Path

import pytest

from tools.character_reference_analysis.asr_coordinator import (
    AsrProcessingOutcome,
    ReferenceAsrCoordinator,
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


class FakeBackend:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def transcribe(
        self,
        media_path: Path,
        *,
        reference_id: str,
        language: str | None = "ja",
    ) -> Transcript:
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider failed")
        return Transcript(
            reference_id=reference_id,
            text="こんにちは。",
            segments=(
                TranscriptSegment(
                    text="こんにちは。",
                    start_seconds=0.0,
                    end_seconds=1.0,
                    language=language,
                    speaker="A",
                ),
            ),
            metadata=TranscriptionMetadata(
                provider="fake",
                model="fake-asr",
                requested_language=language,
                detected_language=language,
                response_format="diarized_json",
                source_duration_seconds=1.0,
            ),
        )


class InMemoryStore:
    def __init__(self) -> None:
        self.manifests: dict[str, ReferenceAnalysisManifest] = {}
        self.transcripts: dict[str, Transcript] = {}

    async def has_revision(self, revision_key: str) -> bool:
        return revision_key in self.manifests

    async def has_transcript(self, revision_key: str) -> bool:
        return revision_key in self.transcripts

    async def load_manifest(
        self, revision_key: str
    ) -> ReferenceAnalysisManifest | None:
        return self.manifests.get(revision_key)

    async def save_manifest(self, manifest: ReferenceAnalysisManifest) -> None:
        self.manifests[manifest.revision_key] = manifest

    async def save_transcript(self, transcript: Transcript, *, revision_key: str) -> None:
        self.transcripts[revision_key] = transcript


def make_source(content_hash: str = "abc") -> ReferenceSource:
    return ReferenceSource(
        reference_id="drive:file-001",
        source_kind=ReferenceSourceKind.GOOGLE_DRIVE_VIDEO,
        source_locator="drive-file:file-001",
        display_name="reference.mov",
        content_hash=content_hash,
    )


def make_transcript(reference_id: str = "drive:file-001") -> Transcript:
    return Transcript(
        reference_id=reference_id,
        text="保存済み文字起こし",
        segments=(),
        metadata=TranscriptionMetadata(
            provider="fake",
            model="fake-asr",
            requested_language="ja",
            detected_language="ja",
            response_format="json",
        ),
    )


@pytest.mark.asyncio
async def test_first_revision_is_transcribed_and_persisted(tmp_path: Path) -> None:
    media = tmp_path / "reference.mov"
    media.write_bytes(b"media")
    backend = FakeBackend()
    store = InMemoryStore()
    coordinator = ReferenceAsrCoordinator(backend=backend, store=store)

    result = await coordinator.process(make_source(), media)

    assert result.outcome == AsrProcessingOutcome.COMPLETED
    assert result.revision_key == "drive:file-001@abc"
    assert backend.calls == 1
    assert store.manifests[result.revision_key].asr_status == AnalysisStepStatus.COMPLETED
    assert store.transcripts[result.revision_key].text == "こんにちは。"


@pytest.mark.asyncio
async def test_same_completed_revision_is_not_transcribed_twice(tmp_path: Path) -> None:
    media = tmp_path / "reference.mov"
    media.write_bytes(b"media")
    backend = FakeBackend()
    store = InMemoryStore()
    coordinator = ReferenceAsrCoordinator(backend=backend, store=store)
    source = make_source()

    first = await coordinator.process(source, media)
    second = await coordinator.process(source, media)

    assert first.outcome == AsrProcessingOutcome.COMPLETED
    assert second.outcome == AsrProcessingOutcome.SKIPPED_DUPLICATE
    assert backend.calls == 1


@pytest.mark.asyncio
async def test_processing_without_transcript_is_recovered_and_reexecuted(
    tmp_path: Path,
) -> None:
    media = tmp_path / "reference.mov"
    media.write_bytes(b"media")
    source = make_source()
    revision_key = build_revision_key(source)
    backend = FakeBackend()
    store = InMemoryStore()
    store.manifests[revision_key] = ReferenceAnalysisManifest.for_source(
        source
    ).with_asr_status(AnalysisStepStatus.PROCESSING)
    coordinator = ReferenceAsrCoordinator(backend=backend, store=store)

    result = await coordinator.process(source, media)

    assert result.outcome == AsrProcessingOutcome.COMPLETED
    assert backend.calls == 1
    assert store.manifests[revision_key].asr_status == AnalysisStepStatus.COMPLETED


@pytest.mark.asyncio
async def test_processing_with_saved_transcript_recovers_without_paid_asr(
    tmp_path: Path,
) -> None:
    media = tmp_path / "reference.mov"
    media.write_bytes(b"media")
    source = make_source()
    revision_key = build_revision_key(source)
    backend = FakeBackend()
    store = InMemoryStore()
    store.manifests[revision_key] = ReferenceAnalysisManifest.for_source(
        source
    ).with_asr_status(AnalysisStepStatus.PROCESSING)
    store.transcripts[revision_key] = make_transcript()
    coordinator = ReferenceAsrCoordinator(backend=backend, store=store)

    result = await coordinator.process(source, media)

    assert result.outcome == AsrProcessingOutcome.SKIPPED_DUPLICATE
    assert backend.calls == 0
    assert store.manifests[revision_key].asr_status == AnalysisStepStatus.COMPLETED


@pytest.mark.asyncio
async def test_changed_content_hash_is_new_revision(tmp_path: Path) -> None:
    media = tmp_path / "reference.mov"
    media.write_bytes(b"media")
    backend = FakeBackend()
    store = InMemoryStore()
    coordinator = ReferenceAsrCoordinator(backend=backend, store=store)

    await coordinator.process(make_source("abc"), media)
    result = await coordinator.process(make_source("def"), media)

    assert result.outcome == AsrProcessingOutcome.COMPLETED
    assert result.revision_key == "drive:file-001@def"
    assert backend.calls == 2


@pytest.mark.asyncio
async def test_failure_is_recorded_and_requires_explicit_retry(tmp_path: Path) -> None:
    media = tmp_path / "reference.mov"
    media.write_bytes(b"media")
    backend = FakeBackend(fail=True)
    store = InMemoryStore()
    coordinator = ReferenceAsrCoordinator(backend=backend, store=store)
    source = make_source()

    failed = await coordinator.process(source, media)
    blocked = await coordinator.process(source, media)

    assert failed.outcome == AsrProcessingOutcome.FAILED
    assert blocked.outcome == AsrProcessingOutcome.FAILED
    assert store.manifests[failed.revision_key].asr_status == AnalysisStepStatus.FAILED
    assert "provider failed" in (store.manifests[failed.revision_key].last_error or "")
    assert backend.calls == 1

    backend.fail = False
    retried = await coordinator.process(source, media, retry=True)

    assert retried.outcome == AsrProcessingOutcome.COMPLETED
    assert backend.calls == 2
