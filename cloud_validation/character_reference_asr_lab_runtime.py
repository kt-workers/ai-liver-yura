from __future__ import annotations

import asyncio
import os
import secrets
import time
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from tools.character_reference_analysis.asr_coordinator import ReferenceAsrCoordinator
from tools.character_reference_analysis.cloud_pipeline import ReferenceCloudAsrPipeline
from tools.character_reference_analysis.google_drive import (
    GoogleDriveReferenceInbox,
    build_google_drive_service,
)
from tools.character_reference_analysis.manifest import build_revision_key
from tools.character_reference_analysis.media_normalizer import FfmpegAudioNormalizer
from tools.character_reference_analysis.models import ReferenceSource
from tools.character_reference_analysis.openai_async_transcription import (
    OpenAIAsyncTranscriptionBackend,
)
from tools.character_reference_analysis.preview_store import GoogleDriveReferencePreviewStore
from tools.character_reference_analysis.progress import ProgressCallback
from tools.character_reference_analysis.recoverable_store import (
    RecoverableGoogleDriveReferenceResultStore,
)
from tools.character_reference_analysis.store import ReferenceResultStore
from tools.character_reference_analysis.thumbnailer import FfmpegReferenceThumbnailer


@dataclass(frozen=True, slots=True)
class LabSettings:
    inbox_folder_id: str
    results_folder_id: str
    asr_model: str
    username: str
    password: str
    asr_timeout_seconds: float = 90.0

    @classmethod
    def from_env(cls) -> "LabSettings":
        inbox = os.getenv("YURA_REFERENCE_DRIVE_INBOX_FOLDER_ID", "").strip()
        results = os.getenv("YURA_REFERENCE_DRIVE_RESULTS_FOLDER_ID", "").strip() or inbox
        timeout_raw = os.getenv("YURA_REFERENCE_ASR_TIMEOUT_SECONDS", "90").strip()
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as error:
            raise ValueError("YURA_REFERENCE_ASR_TIMEOUT_SECONDS must be numeric") from error
        if timeout_seconds <= 0:
            raise ValueError("YURA_REFERENCE_ASR_TIMEOUT_SECONDS must be > 0")
        return cls(
            inbox_folder_id=inbox,
            results_folder_id=results,
            asr_model=os.getenv(
                "YURA_REFERENCE_ASR_MODEL", "gpt-4o-mini-transcribe"
            ).strip(),
            username=os.getenv("YURA_REFERENCE_LAB_USERNAME", "").strip(),
            password=os.getenv("YURA_REFERENCE_LAB_PASSWORD", ""),
            asr_timeout_seconds=timeout_seconds,
        )

    @property
    def auth_configured(self) -> bool:
        return bool(self.username and self.password)

    @property
    def drive_configured(self) -> bool:
        return bool(self.inbox_folder_id and self.results_folder_id)

    @property
    def openai_configured(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))


class ReferencePipeline(Protocol):
    async def list_sources(self) -> tuple[ReferenceSource, ...]: ...

    async def process_source(
        self,
        source: ReferenceSource,
        *,
        language: str | None = "ja",
        retry: bool = False,
        progress_callback: ProgressCallback | None = None,
    ): ...


class ReferencePreviewStore(Protocol):
    async def load(self, revision_key: str) -> tuple[bytes, str] | None: ...

    async def save(
        self,
        revision_key: str,
        content: bytes,
        media_type: str,
    ) -> None: ...


class AnalyzeRequest(BaseModel):
    reference_id: str
    retry: bool = False


@dataclass(slots=True)
class AnalysisJob:
    job_id: str
    reference_id: str
    model: str
    state: str = "queued"
    stage: str = "queued"
    percent: int = 0
    outcome: str | None = None
    error: str | None = None
    transcript_preview: str | None = None
    segment_count: int = 0
    started_monotonic: float | None = None
    finished_elapsed_seconds: int | None = None

    def elapsed_seconds(self) -> int:
        if self.finished_elapsed_seconds is not None:
            return self.finished_elapsed_seconds
        if self.started_monotonic is None:
            return 0
        return max(0, int(time.monotonic() - self.started_monotonic))

    def finish_elapsed(self) -> None:
        self.finished_elapsed_seconds = self.elapsed_seconds()

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "reference_id": self.reference_id,
            "model": self.model,
            "state": self.state,
            "stage": self.stage,
            "percent": self.percent,
            "elapsed_seconds": self.elapsed_seconds(),
            "outcome": self.outcome,
            "error": self.error,
            "transcript_preview": self.transcript_preview,
            "segment_count": self.segment_count,
        }


class CharacterReferenceLabService:
    def __init__(
        self,
        settings: LabSettings,
        *,
        pipeline: ReferencePipeline | None = None,
        store: ReferenceResultStore | None = None,
        preview_store: ReferencePreviewStore | None = None,
    ) -> None:
        self._settings = settings
        self._pipeline = pipeline
        self._store = store
        self._preview_store = preview_store
        self._source_cache: dict[str, ReferenceSource] = {}
        self._jobs: dict[str, AnalysisJob] = {}
        self._active_job_by_reference: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._thumbnail_semaphore = asyncio.Semaphore(2)

    def _ensure_components(self) -> tuple[ReferencePipeline, ReferenceResultStore]:
        if self._pipeline is not None and self._store is not None:
            return self._pipeline, self._store
        if not self._settings.drive_configured:
            raise RuntimeError("Google Drive folder ID is not configured")
        service = build_google_drive_service()
        inbox = GoogleDriveReferenceInbox(
            service=service,
            folder_id=self._settings.inbox_folder_id,
        )
        store = RecoverableGoogleDriveReferenceResultStore(
            service=service,
            folder_id=self._settings.results_folder_id,
        )
        preview_store = GoogleDriveReferencePreviewStore(
            service=service,
            folder_id=self._settings.results_folder_id,
        )
        coordinator = ReferenceAsrCoordinator(
            backend=OpenAIAsyncTranscriptionBackend(
                model=self._settings.asr_model,
                timeout_seconds=self._settings.asr_timeout_seconds,
            ),
            store=store,
        )
        pipeline = ReferenceCloudAsrPipeline(
            inbox=inbox,
            normalizer=FfmpegAudioNormalizer(),
            coordinator=coordinator,
            thumbnailer=FfmpegReferenceThumbnailer(),
        )
        self._pipeline = pipeline
        self._store = store
        self._preview_store = preview_store
        return pipeline, store

    async def _sources(self) -> tuple[ReferenceSource, ...]:
        pipeline, _ = self._ensure_components()
        sources = await pipeline.list_sources()
        self._source_cache = {source.reference_id: source for source in sources}
        return sources

    async def _find_source(self, reference_id: str) -> ReferenceSource:
        source = self._source_cache.get(reference_id)
        if source is not None:
            return source
        sources = await self._sources()
        source = next((item for item in sources if item.reference_id == reference_id), None)
        if source is None:
            raise ValueError("reference_id was not found in the configured Drive folder")
        return source

    async def list_references(self) -> list[dict[str, object]]:
        _, store = self._ensure_components()
        sources = await self._sources()
        items: list[dict[str, object]] = []
        for source in sources:
            revision_key = build_revision_key(source)
            manifest = await store.load_manifest(revision_key)
            active_job = self._active_job(source.reference_id)
            items.append(
                {
                    "reference_id": source.reference_id,
                    "display_name": source.display_name,
                    "source_kind": source.source_kind.value,
                    "revision_key": revision_key,
                    "content_hash": source.content_hash,
                    "size_bytes": source.size_bytes,
                    "duration_seconds": source.duration_seconds,
                    "drive_thumbnail_available": source.thumbnail_available,
                    "preview_available": True,
                    "asr_status": manifest.asr_status.value if manifest else "pending",
                    "audio_analysis_status": (
                        manifest.audio_analysis_status.value if manifest else "pending"
                    ),
                    "visual_analysis_status": (
                        manifest.visual_analysis_status.value if manifest else "pending"
                    ),
                    "analysis_job": active_job.to_dict() if active_job else None,
                    "reference_only": True,
                }
            )
        return items

    def _active_job(self, reference_id: str) -> AnalysisJob | None:
        job_id = self._active_job_by_reference.get(reference_id)
        if job_id is None:
            return None
        job = self._jobs.get(job_id)
        if job is None or job.state not in {"queued", "running"}:
            return None
        return job

    async def thumbnail(self, reference_id: str) -> tuple[bytes, str] | None:
        pipeline, _ = self._ensure_components()
        source = await self._find_source(reference_id)
        revision_key = build_revision_key(source)
        if self._preview_store is not None:
            cached = await self._preview_store.load(revision_key)
            if cached is not None:
                return cached
        if source.thumbnail_available:
            fetcher = getattr(pipeline, "fetch_thumbnail", None)
            if fetcher is not None:
                payload = await fetcher(source)
                if payload is not None:
                    return payload
        generator = getattr(pipeline, "generate_thumbnail", None)
        if generator is None:
            return None
        async with self._thumbnail_semaphore:
            if self._preview_store is not None:
                cached = await self._preview_store.load(revision_key)
                if cached is not None:
                    return cached
            payload = await generator(source)
            if payload is None:
                return None
            if self._preview_store is not None:
                content, media_type = payload
                await self._preview_store.save(revision_key, content, media_type)
            return payload

    async def analyze(self, request: AnalyzeRequest) -> dict[str, object]:
        pipeline, _ = self._ensure_components()
        source = await self._find_source(request.reference_id)
        result = await pipeline.process_source(
            source,
            language="ja",
            retry=request.retry,
        )
        return self._analysis_result(source, result)

    async def start_analysis(self, request: AnalyzeRequest) -> dict[str, object]:
        source = await self._find_source(request.reference_id)
        active = self._active_job(source.reference_id)
        if active is not None:
            return active.to_dict()
        job = AnalysisJob(
            job_id=uuid4().hex,
            reference_id=source.reference_id,
            model=self._settings.asr_model,
        )
        self._jobs[job.job_id] = job
        self._active_job_by_reference[source.reference_id] = job.job_id
        task = asyncio.create_task(
            self._run_analysis_job(job, source, retry=request.retry),
            name=f"reference-analysis-{job.job_id}",
        )
        self._tasks[job.job_id] = task
        task.add_done_callback(
            lambda _task, job_id=job.job_id: self._tasks.pop(job_id, None)
        )
        return job.to_dict()

    async def analysis_progress(self, job_id: str) -> dict[str, object]:
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError("analysis job was not found")
        return job.to_dict()

    async def cancel_analysis(self, job_id: str) -> dict[str, object]:
        job = self._jobs.get(job_id)
        task = self._tasks.get(job_id)
        if job is None:
            raise ValueError("analysis job was not found")
        if task is None or task.done() or job.state not in {"queued", "running"}:
            return job.to_dict()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return job.to_dict()

    async def _run_analysis_job(
        self,
        job: AnalysisJob,
        source: ReferenceSource,
        *,
        retry: bool,
    ) -> None:
        pipeline, _ = self._ensure_components()
        job.state = "running"
        job.stage = "starting"
        job.percent = 1
        job.started_monotonic = time.monotonic()

        async def progress(stage: str, percent: int) -> None:
            job.stage = stage
            job.percent = max(0, min(100, percent))

        try:
            result = await pipeline.process_source(
                source,
                language="ja",
                retry=retry,
                progress_callback=progress,
            )
            result_data = self._analysis_result(source, result)
            job.outcome = str(result_data["outcome"])
            value = result_data["error"]
            job.error = value if isinstance(value, str) else None
            preview = result_data["transcript_preview"]
            job.transcript_preview = preview if isinstance(preview, str) else None
            job.segment_count = int(result_data["segment_count"])
            if job.outcome == "failed":
                job.state = "failed"
                job.stage = "failed"
            elif job.outcome == "skipped_duplicate":
                job.state = "skipped"
                if job.stage not in {"recovered_completed", "retry_required"}:
                    job.stage = "skipped_duplicate"
            else:
                job.state = "completed"
                job.stage = "completed"
            job.percent = 100
        except asyncio.CancelledError:
            job.state = "canceled"
            job.stage = "canceled"
            job.percent = 100
            job.outcome = "canceled"
        except Exception as error:
            job.state = "failed"
            job.stage = "failed"
            job.percent = 100
            job.error = f"{type(error).__name__}: {error}"
        finally:
            job.finish_elapsed()
            if self._active_job_by_reference.get(source.reference_id) == job.job_id:
                self._active_job_by_reference.pop(source.reference_id, None)

    @staticmethod
    def _analysis_result(source: ReferenceSource, result: object) -> dict[str, object]:
        transcript = getattr(result, "transcript", None)
        transcript_preview = None
        segment_count = 0
        if transcript is not None:
            transcript_preview = transcript.text[:240]
            segment_count = len(transcript.segments)
        outcome = getattr(result, "outcome")
        return {
            "reference_id": source.reference_id,
            "display_name": source.display_name,
            "revision_key": getattr(result, "revision_key"),
            "outcome": outcome.value,
            "error": getattr(result, "error"),
            "transcript_preview": transcript_preview,
            "segment_count": segment_count,
            "reference_only": True,
        }


_security = HTTPBasic(auto_error=False)


def create_app(
    *,
    settings: LabSettings | None = None,
    service: CharacterReferenceLabService | None = None,
) -> FastAPI:
    resolved_settings = settings or LabSettings.from_env()
    resolved_service = service or CharacterReferenceLabService(resolved_settings)
    application = FastAPI(
        title="Yura Character Reference ASR Lab",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def require_auth(
        credentials: HTTPBasicCredentials | None = Depends(_security),
    ) -> str:
        if not resolved_settings.auth_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LabのBasic Auth認証情報が未設定です",
            )
        valid = bool(
            credentials
            and secrets.compare_digest(
                credentials.username.encode("utf-8"),
                resolved_settings.username.encode("utf-8"),
            )
            and secrets.compare_digest(
                credentials.password.encode("utf-8"),
                resolved_settings.password.encode("utf-8"),
            )
        )
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="認証に失敗しました",
                headers={"WWW-Authenticate": "Basic"},
            )
        return resolved_settings.username

    @application.get("/healthz")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "auth_configured": resolved_settings.auth_configured,
            "drive_configured": resolved_settings.drive_configured,
            "openai_configured": resolved_settings.openai_configured,
            "asr_model": resolved_settings.asr_model,
            "asr_timeout_seconds": resolved_settings.asr_timeout_seconds,
            "reference_usage": "reference_only",
        }

    @application.get("/", response_class=HTMLResponse)
    async def index(_: str = Depends(require_auth)) -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    @application.get("/api/references")
    async def references(_: str = Depends(require_auth)) -> list[dict[str, object]]:
        try:
            return await resolved_service.list_references()
        except Exception as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @application.get("/api/thumbnail/{reference_id}")
    async def thumbnail(
        reference_id: str,
        _: str = Depends(require_auth),
    ) -> Response:
        try:
            payload = await resolved_service.thumbnail(reference_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        if payload is None:
            raise HTTPException(status_code=404, detail="thumbnail is not available")
        content, media_type = payload
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=86400"},
        )

    @application.post("/api/analyze")
    async def analyze(
        request: AnalyzeRequest,
        _: str = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return await resolved_service.analyze(request)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @application.post("/api/analyze/start")
    async def start_analysis(
        request: AnalyzeRequest,
        _: str = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return await resolved_service.start_analysis(request)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @application.get("/api/analyze/progress/{job_id}")
    async def analysis_progress(
        job_id: str,
        _: str = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return await resolved_service.analysis_progress(job_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @application.post("/api/analyze/cancel/{job_id}")
    async def cancel_analysis(
        job_id: str,
        _: str = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return await resolved_service.cancel_analysis(job_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return application


_INDEX_HTML = r"""
<!doctype html><html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yura Character Reference Lab</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#07131d;color:#eaf7ff}main{width:min(1180px,94vw);margin:auto;padding:28px 0}
h1{margin:0}.note,.status{color:#9ac2d8}.toolbar,.actions,.details{display:flex;gap:8px;flex-wrap:wrap}
.toolbar{margin:14px 0}.card{border:1px solid #294a5d;background:#0a1b27;border-radius:16px;padding:15px;margin:10px 0}
.row{display:grid;grid-template-columns:150px 1fr auto;gap:16px;align-items:center}.name{font-weight:700;font-size:18px}
.details{color:#b7d1df;font-size:13px;margin-top:7px}.meta{color:#8fb5c9;font-size:13px;margin-top:7px}
.thumb{width:150px;height:96px;border-radius:11px;overflow:hidden;background:#061019;border:1px solid #244557;display:flex;align-items:center;justify-content:center;color:#698ca0;font-size:12px}.thumb img{width:100%;height:100%;object-fit:cover}
.badge{display:inline-block;border:1px solid #3e6a82;border-radius:999px;padding:3px 8px;margin-right:5px}
button{border:1px solid #4f809b;background:#10415a;color:#fff;border-radius:10px;padding:9px 13px;cursor:pointer}button:disabled{opacity:.5}.cancel{background:#4b2730;border-color:#8a5663}
.preview{margin-top:8px;color:#c7dfeb;font-size:13px;white-space:pre-wrap;margin-left:166px}.progress-wrap{margin-top:10px}.progress-line{display:flex;justify-content:space-between;gap:10px;color:#9fc7da;font-size:12px;margin-bottom:5px}.progress-extra{color:#789fb3;font-size:12px;margin-top:5px}.progress-track{height:8px;border-radius:999px;background:#061019;border:1px solid #244557;overflow:hidden}.progress-bar{height:100%;width:0;background:#3d819f;transition:width .25s ease}
@media(max-width:700px){.row{grid-template-columns:100px 1fr}.thumb{width:100px;height:72px}.actions{grid-column:2}.preview{margin-left:116px}}
</style></head><body><main>
<h1>Character Reference Lab</h1><div class="note">参考動画 → 日本語ASR。素材はreference-onlyで、ゆらへ直接コピーしません。</div>
<div class="toolbar"><button id="refresh">再読込</button><button id="all">未処理を順番に解析</button></div>
<div id="status" class="status"></div><div id="list"></div>
<script>
const $=id=>document.getElementById(id);let items=[];const jobs=new Map();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stages={queued:'待機',starting:'開始',downloading_video:'動画を取得中',video_downloaded:'動画取得完了',extracting_audio:'音声を抽出中',audio_extracted:'音声抽出完了',checking_duplicate:'重複解析を確認中',preparing_asr:'ASRを準備中',transcribing:'日本語ASR処理中',saving_transcript:'解析結果をDriveへ保存中',finalizing:'最終状態を保存中',completed:'完了',failed:'失敗',canceled:'キャンセル済み',skipped_duplicate:'解析済みのためスキップ',recovered_completed:'保存済み結果から復旧',retry_required:'再試行が必要'};
function bytes(v){if(v==null)return 'サイズ: —';let n=Number(v),u=['B','KB','MB','GB'],i=0;while(n>=1024&&i<3){n/=1024;i++}return `サイズ: ${n.toFixed(i&&n<100?1:0)} ${u[i]}`}
function duration(v){if(v==null)return '長さ: —';let t=Math.max(0,Math.round(Number(v))),m=Math.floor(t/60),s=t%60;return `長さ: ${m}:${String(s).padStart(2,'0')}`}
function elapsed(v){let t=Math.max(0,Number(v)||0),m=Math.floor(t/60),s=Math.floor(t%60);return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`}
async function load(){ $('status').textContent='読込中…';const r=await fetch('/api/references'),p=await r.json();if(!r.ok)throw new Error(p.detail||r.status);items=p;for(const x of items)if(x.analysis_job)jobs.set(x.reference_id,x.analysis_job);render();$('status').textContent=`${items.length}件`;}
function thumb(x){return `<div class="thumb"><img src="/api/thumbnail/${encodeURIComponent(x.reference_id)}" alt="" loading="lazy" onerror="this.parentElement.textContent='No preview'"></div>`}
function progress(x,i){const j=jobs.get(x.reference_id);if(!j)return `<div id="progress${i}" class="progress-wrap" hidden></div>`;return `<div id="progress${i}" class="progress-wrap"><div class="progress-line"><span>${esc(stages[j.stage]||j.stage)}</span><span>${Number(j.percent)||0}%</span></div><div class="progress-track"><div class="progress-bar" style="width:${Number(j.percent)||0}%"></div></div><div class="progress-extra">経過 ${elapsed(j.elapsed_seconds)} ・ ${esc(j.model||'')}</div></div>`}
function result(x){const j=jobs.get(x.reference_id);if(!j)return '';if(j.error)return esc(j.error);if(j.transcript_preview)return `${esc(j.outcome||'')} / segments=${Number(j.segment_count)||0}\n${esc(j.transcript_preview)}`;return esc(j.outcome||'')}
function render(){ $('list').innerHTML=items.map((x,i)=>{const j=jobs.get(x.reference_id),active=j&&['queued','running'].includes(j.state);return `<div class="card"><div class="row">${thumb(x)}<div><div class="name">${esc(x.display_name)}</div><div class="details"><span>${duration(x.duration_seconds)}</span><span>${bytes(x.size_bytes)}</span></div><div class="meta"><span class="badge">ASR: ${esc(x.asr_status)}</span><span class="badge">audio: ${esc(x.audio_analysis_status)}</span><span class="badge">visual: ${esc(x.visual_analysis_status)}</span></div>${progress(x,i)}</div><div class="actions"><button id="run${i}" onclick="run(${i})" ${active?'disabled':''}>解析</button><button class="cancel" id="cancel${i}" onclick="cancelJob(${i})" ${active?'':'hidden'}>キャンセル</button></div></div><div class="preview">${result(x)}</div></div>`}).join('')}
function update(i,j){jobs.set(items[i].reference_id,j);render()}
async function poll(i,id){while(true){const r=await fetch(`/api/analyze/progress/${encodeURIComponent(id)}`),j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);update(i,j);if(!['queued','running'].includes(j.state)){await load();return j}await new Promise(ok=>setTimeout(ok,1000))}}
async function run(i){const x=items[i],retry=x.asr_status==='failed';$('status').textContent=`解析開始: ${x.display_name}`;const r=await fetch('/api/analyze/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({reference_id:x.reference_id,retry})}),j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);update(i,j);const done=await poll(i,j.job_id);$('status').textContent=done.state==='failed'?`失敗: ${x.display_name}`:done.state==='canceled'?`キャンセル: ${x.display_name}`:`完了: ${x.display_name}`;return done}
async function cancelJob(i){const j=jobs.get(items[i].reference_id);if(!j)return;const r=await fetch(`/api/analyze/cancel/${encodeURIComponent(j.job_id)}`,{method:'POST'}),p=await r.json();if(!r.ok)throw new Error(p.detail||r.status);update(i,p)}
$('refresh').onclick=()=>load().catch(e=>$('status').textContent=`失敗: ${e.message}`);
$('all').onclick=async()=>{ $('all').disabled=true;try{for(let i=0;i<items.length;i++)if(['pending','failed','interrupted'].includes(items[i].asr_status))await run(i);$('status').textContent='未処理の解析が完了しました'}catch(e){$('status').textContent=`失敗: ${e.message}`}finally{$('all').disabled=false}};
load().catch(e=>$('status').textContent=`初期化失敗: ${e.message}`);
</script></main></body></html>
"""


app = create_app()
