from __future__ import annotations

import asyncio
import os
import secrets
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
    GoogleDriveReferenceResultStore,
    build_google_drive_service,
)
from tools.character_reference_analysis.manifest import build_revision_key
from tools.character_reference_analysis.media_normalizer import FfmpegAudioNormalizer
from tools.character_reference_analysis.models import ReferenceSource
from tools.character_reference_analysis.openai_transcription import OpenAITranscriptionBackend
from tools.character_reference_analysis.preview_store import GoogleDriveReferencePreviewStore
from tools.character_reference_analysis.progress import ProgressCallback
from tools.character_reference_analysis.store import ReferenceResultStore
from tools.character_reference_analysis.thumbnailer import FfmpegReferenceThumbnailer


@dataclass(frozen=True, slots=True)
class LabSettings:
    inbox_folder_id: str
    results_folder_id: str
    asr_model: str
    username: str
    password: str

    @classmethod
    def from_env(cls) -> "LabSettings":
        inbox = os.getenv("YURA_REFERENCE_DRIVE_INBOX_FOLDER_ID", "").strip()
        results = os.getenv("YURA_REFERENCE_DRIVE_RESULTS_FOLDER_ID", "").strip() or inbox
        return cls(
            inbox_folder_id=inbox,
            results_folder_id=results,
            asr_model=os.getenv(
                "YURA_REFERENCE_ASR_MODEL", "gpt-4o-transcribe-diarize"
            ).strip(),
            username=os.getenv("YURA_REFERENCE_LAB_USERNAME", "").strip(),
            password=os.getenv("YURA_REFERENCE_LAB_PASSWORD", ""),
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
    state: str = "queued"
    stage: str = "queued"
    percent: int = 0
    outcome: str | None = None
    error: str | None = None
    transcript_preview: str | None = None
    segment_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "reference_id": self.reference_id,
            "state": self.state,
            "stage": self.stage,
            "percent": self.percent,
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
        store = GoogleDriveReferenceResultStore(
            service=service,
            folder_id=self._settings.results_folder_id,
        )
        preview_store = GoogleDriveReferencePreviewStore(
            service=service,
            folder_id=self._settings.results_folder_id,
        )
        coordinator = ReferenceAsrCoordinator(
            backend=OpenAITranscriptionBackend(model=self._settings.asr_model),
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
        source = next(
            (item for item in sources if item.reference_id == reference_id),
            None,
        )
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
                    "asr_status": (
                        manifest.asr_status.value if manifest is not None else "pending"
                    ),
                    "audio_analysis_status": (
                        manifest.audio_analysis_status.value
                        if manifest is not None
                        else "pending"
                    ),
                    "visual_analysis_status": (
                        manifest.visual_analysis_status.value
                        if manifest is not None
                        else "pending"
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
                await self._preview_store.save(
                    revision_key,
                    content,
                    media_type,
                )
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
            job.error = result_data["error"] if isinstance(result_data["error"], str) else None
            preview = result_data["transcript_preview"]
            job.transcript_preview = preview if isinstance(preview, str) else None
            job.segment_count = int(result_data["segment_count"])
            if job.outcome == "failed":
                job.state = "failed"
                job.stage = "failed"
            elif job.outcome == "skipped_duplicate":
                job.state = "skipped"
                job.stage = "skipped_duplicate"
            else:
                job.state = "completed"
                job.stage = "completed"
            job.percent = 100
        except Exception as error:
            job.state = "failed"
            job.stage = "failed"
            job.percent = 100
            job.error = f"{type(error).__name__}: {error}"
        finally:
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
        version="0.1.0",
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
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @application.get("/api/thumbnail/{reference_id}")
    async def thumbnail(
        reference_id: str,
        _: str = Depends(require_auth),
    ) -> Response:
        try:
            payload = await resolved_service.thumbnail(reference_id)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="thumbnail is not available",
            )
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @application.post("/api/analyze/start")
    async def start_analysis(
        request: AnalyzeRequest,
        _: str = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return await resolved_service.start_analysis(request)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @application.get("/api/analyze/progress/{job_id}")
    async def analysis_progress(
        job_id: str,
        _: str = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return await resolved_service.analysis_progress(job_id)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    return application


app = create_app()


_INDEX_HTML = r"""
<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yura Character Reference Lab</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#07131d;color:#eaf7ff}main{width:min(1180px,94vw);margin:auto;padding:28px 0}
header{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:18px}
h1{margin:0}.note{color:#9ac2d8}.card{border:1px solid #294a5d;background:#0a1b27;border-radius:16px;padding:15px;margin:10px 0}
.row{display:grid;grid-template-columns:150px 1fr auto;gap:16px;align-items:center}.name{font-weight:700}.meta{color:#8fb5c9;font-size:13px;margin-top:7px}
.details{display:flex;gap:12px;flex-wrap:wrap;color:#b7d1df;font-size:13px;margin-top:7px}.detail{white-space:nowrap}
.thumb{width:150px;height:96px;border-radius:11px;overflow:hidden;background:#061019;border:1px solid #244557;display:flex;align-items:center;justify-content:center;color:#698ca0;font-size:12px}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}.badge{display:inline-block;border:1px solid #3e6a82;border-radius:999px;padding:3px 8px;margin-right:5px;font-size:12px}
button{border:1px solid #4f809b;background:#10415a;color:#fff;border-radius:10px;padding:9px 13px;cursor:pointer}button:disabled{opacity:.5}
.toolbar{display:flex;gap:8px;margin:14px 0}.status{min-height:24px;color:#a5cde2;white-space:pre-wrap}.preview{margin-top:8px;color:#c7dfeb;font-size:13px;white-space:pre-wrap;margin-left:166px}
.progress-wrap{margin-top:10px}.progress-line{display:flex;justify-content:space-between;gap:10px;color:#9fc7da;font-size:12px;margin-bottom:5px}.progress-track{height:8px;border-radius:999px;background:#061019;border:1px solid #244557;overflow:hidden}.progress-bar{height:100%;width:0;background:#3d819f;transition:width .25s ease}
@media(max-width:700px){.row{grid-template-columns:100px 1fr}.thumb{width:100px;height:72px}.row>button{grid-column:2;justify-self:start}.preview{margin-left:116px}}
</style></head><body><main>
<header><div><h1>Character Reference Lab</h1><div class="note">参考動画 → 日本語ASR。素材はreference-onlyで、ゆらへ直接コピーしません。</div></div></header>
<div class="toolbar"><button id="refresh">再読込</button><button id="all">未処理を順番に解析</button></div>
<div id="status" class="status"></div><div id="list"></div>
<script>
const $=id=>document.getElementById(id);let items=[];const jobResults=new Map();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stageNames={queued:'待機',starting:'開始',downloading_video:'動画を取得中',video_downloaded:'動画取得完了',extracting_audio:'音声を抽出中',audio_extracted:'音声抽出完了',checking_duplicate:'重複解析を確認中',preparing_asr:'ASRを準備中',transcribing:'日本語ASR処理中',saving_transcript:'解析結果をDriveへ保存中',finalizing:'最終状態を保存中',completed:'完了',failed:'失敗',skipped_duplicate:'解析済みのためスキップ'};
function formatBytes(value){if(value===null||value===undefined)return 'サイズ: —';let n=Number(value);if(!Number.isFinite(n))return 'サイズ: —';const units=['B','KB','MB','GB'];let i=0;while(n>=1024&&i<units.length-1){n/=1024;i++;}const digits=i===0?0:(n>=100?0:n>=10?1:2);return `サイズ: ${n.toFixed(digits)} ${units[i]}`;}
function formatDuration(value){if(value===null||value===undefined)return '長さ: —';const total=Math.max(0,Math.round(Number(value)));if(!Number.isFinite(total))return '長さ: —';const h=Math.floor(total/3600),m=Math.floor((total%3600)/60),s=total%60;return `長さ: ${h?`${h}:`:''}${h?String(m).padStart(2,'0'):m}:${String(s).padStart(2,'0')}`;}
async function load(){ $('status').textContent='読込中…'; const r=await fetch('/api/references'); const p=await r.json(); if(!r.ok)throw new Error(p.detail||r.status); items=p; for(const x of items){if(x.analysis_job)jobResults.set(x.reference_id,x.analysis_job);} render(); $('status').textContent=`${items.length}件`; }
function thumb(x){const src=`/api/thumbnail/${encodeURIComponent(x.reference_id)}`;return `<div class="thumb"><img src="${src}" alt="" loading="lazy" onerror="this.parentElement.textContent='No preview'"></div>`;}
function progressHtml(x,i){const j=jobResults.get(x.reference_id);if(!j)return `<div id="progress${i}" class="progress-wrap" hidden><div class="progress-line"><span id="stage${i}"></span><span id="pct${i}"></span></div><div class="progress-track"><div id="bar${i}" class="progress-bar"></div></div></div>`;const hidden=(j.state==='completed'||j.state==='skipped')?'':' ';return `<div id="progress${i}" class="progress-wrap"${hidden?'':' hidden'}><div class="progress-line"><span id="stage${i}">${esc(stageNames[j.stage]||j.stage)}</span><span id="pct${i}">${Number(j.percent)||0}%</span></div><div class="progress-track"><div id="bar${i}" class="progress-bar" style="width:${Number(j.percent)||0}%"></div></div></div>`;}
function resultHtml(x){const j=jobResults.get(x.reference_id);if(!j)return '';if(j.error)return esc(j.error);if(j.transcript_preview)return `${esc(j.outcome||'')} / segments=${Number(j.segment_count)||0}\n${esc(j.transcript_preview)}`;if(j.outcome)return esc(j.outcome);return '';}
function render(){ $('list').innerHTML=items.map((x,i)=>`<div class="card"><div class="row">${thumb(x)}<div><div class="name">${esc(x.display_name)}</div><div class="details"><span class="detail">${formatDuration(x.duration_seconds)}</span><span class="detail">${formatBytes(x.size_bytes)}</span></div><div class="meta"><span class="badge">ASR: ${esc(x.asr_status)}</span><span class="badge">audio: ${esc(x.audio_analysis_status)}</span><span class="badge">visual: ${esc(x.visual_analysis_status)}</span></div>${progressHtml(x,i)}</div><button id="run${i}" onclick="run(${i})">解析</button></div><div id="p${i}" class="preview">${resultHtml(x)}</div></div>`).join(''); }
function updateProgress(i,j){jobResults.set(items[i].reference_id,j);const box=$('progress'+i),bar=$('bar'+i),stage=$('stage'+i),pct=$('pct'+i),button=$('run'+i);if(box)box.hidden=false;if(bar)bar.style.width=`${j.percent}%`;if(stage)stage.textContent=stageNames[j.stage]||j.stage;if(pct)pct.textContent=`${j.percent}%`;if(button)button.disabled=(j.state==='queued'||j.state==='running');if(j.error&&$('p'+i))$('p'+i).textContent=j.error;}
async function poll(i,jobId){while(true){const r=await fetch(`/api/analyze/progress/${encodeURIComponent(jobId)}`);const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);updateProgress(i,j);if(!['queued','running'].includes(j.state)){if(j.state==='completed')items[i].asr_status='completed';if(j.state==='failed')items[i].asr_status='failed';if(j.transcript_preview&&$('p'+i))$('p'+i).textContent=`${j.outcome||''} / segments=${j.segment_count}\n${j.transcript_preview}`;render();return j;}await new Promise(resolve=>setTimeout(resolve,700));}}
async function run(i,retry=false){const x=items[i];$('status').textContent=`解析開始: ${x.display_name}`;const r=await fetch('/api/analyze/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({reference_id:x.reference_id,retry})});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);updateProgress(i,j);const done=await poll(i,j.job_id);$('status').textContent=done.state==='failed'?`失敗: ${x.display_name}`:`完了: ${x.display_name}`;return done;}
$('refresh').onclick=()=>load().catch(e=>$('status').textContent=`失敗: ${e.message}`);
$('all').onclick=async()=>{ $('all').disabled=true; try{ for(let i=0;i<items.length;i++){ if(items[i].asr_status==='pending'||items[i].asr_status==='failed') await run(i,items[i].asr_status==='failed'); } $('status').textContent='未処理の解析が完了しました'; }catch(e){ $('status').textContent=`失敗: ${e.message}`; }finally{$('all').disabled=false;} };
load().catch(e=>$('status').textContent=`初期化失敗: ${e.message}`);
</script></main></body></html>
"""
