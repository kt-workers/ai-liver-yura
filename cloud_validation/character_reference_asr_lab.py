from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, FastAPI, HTTPException, status
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
from tools.character_reference_analysis.store import ReferenceResultStore


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
    ): ...


class AnalyzeRequest(BaseModel):
    reference_id: str
    retry: bool = False


class CharacterReferenceLabService:
    def __init__(
        self,
        settings: LabSettings,
        *,
        pipeline: ReferencePipeline | None = None,
        store: ReferenceResultStore | None = None,
    ) -> None:
        self._settings = settings
        self._pipeline = pipeline
        self._store = store

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
        coordinator = ReferenceAsrCoordinator(
            backend=OpenAITranscriptionBackend(model=self._settings.asr_model),
            store=store,
        )
        pipeline = ReferenceCloudAsrPipeline(
            inbox=inbox,
            normalizer=FfmpegAudioNormalizer(),
            coordinator=coordinator,
        )
        self._pipeline = pipeline
        self._store = store
        return pipeline, store

    async def list_references(self) -> list[dict[str, object]]:
        pipeline, store = self._ensure_components()
        sources = await pipeline.list_sources()
        items: list[dict[str, object]] = []
        for source in sources:
            revision_key = build_revision_key(source)
            manifest = await store.load_manifest(revision_key)
            items.append(
                {
                    "reference_id": source.reference_id,
                    "display_name": source.display_name,
                    "source_kind": source.source_kind.value,
                    "revision_key": revision_key,
                    "content_hash": source.content_hash,
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
                    "reference_only": True,
                }
            )
        return items

    async def analyze(self, request: AnalyzeRequest) -> dict[str, object]:
        pipeline, _ = self._ensure_components()
        sources = await pipeline.list_sources()
        source = next(
            (item for item in sources if item.reference_id == request.reference_id),
            None,
        )
        if source is None:
            raise ValueError("reference_id was not found in the configured Drive folder")
        result = await pipeline.process_source(
            source,
            language="ja",
            retry=request.retry,
        )
        transcript_preview = None
        segment_count = 0
        if result.transcript is not None:
            transcript_preview = result.transcript.text[:240]
            segment_count = len(result.transcript.segments)
        return {
            "reference_id": source.reference_id,
            "display_name": source.display_name,
            "revision_key": result.revision_key,
            "outcome": result.outcome.value,
            "error": result.error,
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

    return application


app = create_app()


_INDEX_HTML = r"""
<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yura Character Reference Lab</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#07131d;color:#eaf7ff}main{width:min(1100px,94vw);margin:auto;padding:28px 0}
header{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:18px}
h1{margin:0}.note{color:#9ac2d8}.card{border:1px solid #294a5d;background:#0a1b27;border-radius:16px;padding:15px;margin:10px 0}
.row{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center}.name{font-weight:700}.meta{color:#8fb5c9;font-size:13px;margin-top:5px}
.badge{display:inline-block;border:1px solid #3e6a82;border-radius:999px;padding:3px 8px;margin-right:5px;font-size:12px}
button{border:1px solid #4f809b;background:#10415a;color:#fff;border-radius:10px;padding:9px 13px;cursor:pointer}button:disabled{opacity:.5}
.toolbar{display:flex;gap:8px;margin:14px 0}.status{min-height:24px;color:#a5cde2;white-space:pre-wrap}.preview{margin-top:8px;color:#c7dfeb;font-size:13px;white-space:pre-wrap}
</style></head><body><main>
<header><div><h1>Character Reference Lab</h1><div class="note">参考動画 → 日本語ASR。素材はreference-onlyで、ゆらへ直接コピーしません。</div></div></header>
<div class="toolbar"><button id="refresh">再読込</button><button id="all">未処理を順番に解析</button></div>
<div id="status" class="status"></div><div id="list"></div>
<script>
const $=id=>document.getElementById(id);let items=[];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function load(){ $('status').textContent='読込中…'; const r=await fetch('/api/references'); const p=await r.json(); if(!r.ok)throw new Error(p.detail||r.status); items=p; render(); $('status').textContent=`${items.length}件`; }
function render(){ $('list').innerHTML=items.map((x,i)=>`<div class="card"><div class="row"><div><div class="name">${esc(x.display_name)}</div><div class="meta"><span class="badge">ASR: ${esc(x.asr_status)}</span><span class="badge">audio: ${esc(x.audio_analysis_status)}</span><span class="badge">visual: ${esc(x.visual_analysis_status)}</span></div></div><button onclick="run(${i})">解析</button></div><div id="p${i}" class="preview"></div></div>`).join(''); }
async function run(i,retry=false){ const x=items[i]; $('status').textContent=`解析中: ${x.display_name}`; const r=await fetch('/api/analyze',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({reference_id:x.reference_id,retry})}); const p=await r.json(); if(!r.ok)throw new Error(p.detail||r.status); $('p'+i).textContent=`${p.outcome} / segments=${p.segment_count}\n${p.transcript_preview||''}`; await load(); return p; }
$('refresh').onclick=()=>load().catch(e=>$('status').textContent=`失敗: ${e.message}`);
$('all').onclick=async()=>{ $('all').disabled=true; try{ for(let i=0;i<items.length;i++){ if(items[i].asr_status==='pending'||items[i].asr_status==='failed') await run(i,items[i].asr_status==='failed'); } $('status').textContent='未処理の解析が完了しました'; }catch(e){ $('status').textContent=`失敗: ${e.message}`; }finally{$('all').disabled=false;} };
load().catch(e=>$('status').textContent=`初期化失敗: ${e.message}`);
</script></main></body></html>
"""
