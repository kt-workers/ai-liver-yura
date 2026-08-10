from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from cloud_validation.character_reference_asr_lab import (
    AnalyzeRequest,
    CharacterReferenceLabService,
    LabSettings,
)
from tools.character_reference_analysis.asr_coordinator import ReferenceAsrCoordinator
from tools.character_reference_analysis.manifest import (
    AnalysisStepStatus,
    ReferenceAnalysisManifest,
    build_revision_key,
)
from tools.character_reference_analysis.models import ReferenceSource, ReferenceSourceKind
from tools.character_reference_analysis.openai_async_transcription import (
    OpenAIAsyncTranscriptionBackend,
)
from tools.character_reference_analysis.openai_transcription import OpenAITranscriptionError


def make_source() -> ReferenceSource:
    return ReferenceSource(
        reference_id="drive:resilience",
        source_kind=ReferenceSourceKind.GOOGLE_DRIVE_VIDEO,
        source_locator="drive-file:resilience",
        display_name="resilience.mov",
        content_hash="md5:resilience",
    )


class SlowTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"text": "遅い応答"}, request=request)


@pytest.mark.asyncio
async def test_async_openai_backend_has_strict_total_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    media = tmp_path / "reference.mp3"
    media.write_bytes(b"audio")
    backend = OpenAIAsyncTranscriptionBackend(
        timeout_seconds=0.01,
        transport=SlowTransport(),
    )

    with pytest.raises(OpenAITranscriptionError, match="timed out"):
        await backend.transcribe(media, reference_id="drive:test", language="ja")


def test_async_openai_backend_defaults_to_mini_model() -> None:
    backend = OpenAIAsyncTranscriptionBackend()

    response_format, fields = backend._request_fields("ja")

    assert response_format == "json"
    assert ("model", "gpt-4o-mini-transcribe") in fields


class BlockingBackend:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def transcribe(self, media_path: Path, *, reference_id: str, language="ja"):
        del media_path, reference_id, language
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class InMemoryStore:
    def __init__(self) -> None:
        self.manifests: dict[str, ReferenceAnalysisManifest] = {}

    async def has_revision(self, revision_key: str) -> bool:
        return revision_key in self.manifests

    async def has_transcript(self, revision_key: str) -> bool:
        del revision_key
        return False

    async def load_manifest(self, revision_key: str):
        return self.manifests.get(revision_key)

    async def save_manifest(self, manifest: ReferenceAnalysisManifest) -> None:
        self.manifests[manifest.revision_key] = manifest

    async def save_transcript(self, transcript, *, revision_key: str) -> None:
        del transcript, revision_key


@pytest.mark.asyncio
async def test_coordinator_cancellation_marks_manifest_interrupted(tmp_path: Path) -> None:
    source = make_source()
    media = tmp_path / "reference.mp3"
    media.write_bytes(b"audio")
    backend = BlockingBackend()
    store = InMemoryStore()
    coordinator = ReferenceAsrCoordinator(backend=backend, store=store)

    task = asyncio.create_task(coordinator.process(source, media))
    await backend.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    manifest = store.manifests[build_revision_key(source)]
    assert manifest.asr_status == AnalysisStepStatus.INTERRUPTED


class WaitingPipeline:
    def __init__(self, source: ReferenceSource) -> None:
        self.source = source
        self.started = asyncio.Event()

    async def list_sources(self):
        return (self.source,)

    async def process_source(
        self,
        source: ReferenceSource,
        *,
        language="ja",
        retry=False,
        progress_callback=None,
    ):
        del source, language, retry
        if progress_callback is not None:
            await progress_callback("transcribing", 60)
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_lab_cancel_finishes_background_job_as_canceled() -> None:
    source = make_source()
    pipeline = WaitingPipeline(source)
    service = CharacterReferenceLabService(
        LabSettings(
            inbox_folder_id="inbox",
            results_folder_id="results",
            asr_model="gpt-4o-mini-transcribe",
            username="user",
            password="pass",
        ),
        pipeline=pipeline,
        store=InMemoryStore(),
    )

    started = await service.start_analysis(AnalyzeRequest(reference_id=source.reference_id))
    await pipeline.started.wait()
    canceled = await service.cancel_analysis(str(started["job_id"]))

    assert canceled["state"] == "canceled"
    assert canceled["stage"] == "canceled"
    assert canceled["percent"] == 100
    assert canceled["outcome"] == "canceled"
