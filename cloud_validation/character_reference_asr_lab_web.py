from __future__ import annotations

import base64
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from cloud_validation.character_reference_asr_lab_runtime import (
    AnalyzeRequest,
    AnalysisJob,
    CharacterReferenceLabService as RuntimeCharacterReferenceLabService,
    LabSettings,
)
from cloud_validation.character_reference_lab_session import CharacterReferenceLabSession
from tools.character_reference_analysis.manifest import AnalysisStepStatus, build_revision_key

_COOKIE_NAME = "yura_reference_lab_session"


class LoginRequest(BaseModel):
    username: str
    password: str


class CharacterReferenceLabService(RuntimeCharacterReferenceLabService):
    """Web-facing service that keeps one broken manifest from hiding the full inbox."""

    async def list_references(self) -> list[dict[str, object]]:
        _, store = self._ensure_components()
        sources = await self._sources()
        items: list[dict[str, object]] = []
        for source in sources:
            revision_key = build_revision_key(source)
            active_job = self._active_job(source.reference_id)
            manifest = None
            manifest_error: str | None = None
            try:
                manifest = await store.load_manifest(revision_key)
            except Exception as error:  # one stale result must not break the whole Lab list
                manifest_error = f"{type(error).__name__}: {error}"

            asr_status = manifest.asr_status.value if manifest else "pending"
            if (
                manifest is not None
                and manifest.asr_status == AnalysisStepStatus.PROCESSING
                and active_job is None
            ):
                # A process-local job cannot survive a Render restart. Expose the stale
                # processing state as interrupted without pretending it completed.
                asr_status = AnalysisStepStatus.INTERRUPTED.value

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
                    "asr_status": asr_status,
                    "audio_analysis_status": (
                        manifest.audio_analysis_status.value if manifest else "pending"
                    ),
                    "visual_analysis_status": (
                        manifest.visual_analysis_status.value if manifest else "pending"
                    ),
                    "analysis_job": active_job.to_dict() if active_job else None,
                    "manifest_error": manifest_error,
                    "reference_only": True,
                }
            )
        return items


def create_app(
    *,
    settings: LabSettings | None = None,
    service: CharacterReferenceLabService | None = None,
) -> FastAPI:
    resolved_settings = settings or LabSettings.from_env()
    resolved_service = service or CharacterReferenceLabService(resolved_settings)
    sessions = CharacterReferenceLabSession(
        username=resolved_settings.username,
        password=resolved_settings.password,
    )
    application = FastAPI(
        title="Yura Character Reference ASR Lab",
        version="0.3.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def authenticated(request: Request) -> str:
        if not sessions.configured:
            raise HTTPException(status_code=503, detail="Lab認証情報が未設定です")
        if sessions.validate(request.cookies.get(_COOKIE_NAME)):
            return resolved_settings.username
        raise HTTPException(status_code=401, detail="Lab session is required")

    @application.get("/healthz")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "auth_configured": sessions.configured,
            "auth_mode": "persistent_cookie",
            "drive_configured": resolved_settings.drive_configured,
            "openai_configured": resolved_settings.openai_configured,
            "asr_model": resolved_settings.asr_model,
            "asr_timeout_seconds": resolved_settings.asr_timeout_seconds,
            "reference_usage": "reference_only",
        }

    @application.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        token = request.cookies.get(_COOKIE_NAME)
        if sessions.validate(token):
            return HTMLResponse(_INDEX_HTML)

        basic = _parse_basic_credentials(request.headers.get("authorization"))
        if basic is not None and sessions.validate_credentials(*basic):
            response = HTMLResponse(_INDEX_HTML)
            _set_session_cookie(response, sessions.issue(), sessions.ttl_seconds)
            return response
        return HTMLResponse(_LOGIN_HTML)

    @application.post("/api/session")
    async def login(payload: LoginRequest) -> Response:
        if not sessions.validate_credentials(payload.username, payload.password):
            raise HTTPException(status_code=401, detail="ユーザー名またはパスワードが違います")
        response = Response(content='{"ok":true}', media_type="application/json")
        _set_session_cookie(response, sessions.issue(), sessions.ttl_seconds)
        return response

    @application.get("/api/references")
    async def references(_: str = Depends(authenticated)) -> list[dict[str, object]]:
        try:
            return await resolved_service.list_references()
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail=f"{type(error).__name__}: {error}",
            ) from error

    @application.get("/api/thumbnail")
    async def thumbnail(
        reference_id: str = Query(...),
        _: str = Depends(authenticated),
    ) -> Response:
        try:
            payload = await resolved_service.thumbnail(reference_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail=f"{type(error).__name__}: {error}",
            ) from error
        if payload is None:
            raise HTTPException(status_code=404, detail="thumbnail is not available")
        content, media_type = payload
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=86400"},
        )

    @application.post("/api/analyze/start")
    async def start_analysis(
        payload: AnalyzeRequest,
        _: str = Depends(authenticated),
    ) -> dict[str, object]:
        try:
            return await resolved_service.start_analysis(payload)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail=f"{type(error).__name__}: {error}",
            ) from error

    @application.get("/api/analyze/progress/{job_id}")
    async def analysis_progress(
        job_id: str,
        _: str = Depends(authenticated),
    ) -> dict[str, object]:
        try:
            return await resolved_service.analysis_progress(job_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @application.post("/api/analyze/cancel/{job_id}")
    async def cancel_analysis(
        job_id: str,
        _: str = Depends(authenticated),
    ) -> dict[str, object]:
        try:
            return await resolved_service.cancel_analysis(job_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return application


def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _parse_basic_credentials(value: str | None) -> tuple[str, str] | None:
    if not value or not value.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(value[6:], validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    return username, password


_LOGIN_HTML = """
<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Character Reference Lab</title><style>
:root{font-family:Inter,system-ui,sans-serif;color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#07131d;color:#eaf7ff;display:grid;min-height:100vh;place-items:center}
main{width:min(420px,92vw);background:#0a1b27;border:1px solid #294a5d;border-radius:18px;padding:24px}
h1{margin:0 0 8px}.note,.status{color:#9ac2d8}label{display:block;margin-top:14px}
input{width:100%;margin-top:6px;padding:11px;border-radius:10px;border:1px solid #3e6a82;background:#061019;color:#fff}
button{width:100%;margin-top:18px;padding:11px;border:1px solid #4f809b;background:#10415a;color:#fff;border-radius:10px;cursor:pointer}
</style></head><body><main><h1>Character Reference Lab</h1>
<div class="note">このブラウザでは認証を長期間保持します。通常は次回から入力不要です。</div>
<form id="login"><label>ユーザー名<input id="username" autocomplete="username"></label>
<label>パスワード<input id="password" type="password" autocomplete="current-password"></label>
<button>このブラウザを認証</button></form><div id="status" class="status"></div>
<script>
document.getElementById('login').onsubmit=async e=>{e.preventDefault();const status=document.getElementById('status');status.textContent='認証中…';const r=await fetch('/api/session',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value})});let p={};try{p=await r.json()}catch{}if(!r.ok){status.textContent='失敗: '+(p.detail||r.status);return}location.reload()};
</script></main></body></html>
"""


_INDEX_HTML = r"""
<!doctype html><html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yura Character Reference Lab</title><style>
:root{font-family:Inter,system-ui,sans-serif;color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#07131d;color:#eaf7ff}main{width:min(1180px,94vw);margin:auto;padding:28px 0}
h1{margin:0}.note,.status{color:#9ac2d8}.toolbar,.actions,.details{display:flex;gap:8px;flex-wrap:wrap}.toolbar{margin:14px 0}
.card{border:1px solid #294a5d;background:#0a1b27;border-radius:16px;padding:15px;margin:10px 0}.row{display:grid;grid-template-columns:150px 1fr auto;gap:16px;align-items:center}.name{font-weight:700;font-size:18px}.details{color:#b7d1df;font-size:13px;margin-top:7px}.meta{color:#8fb5c9;font-size:13px;margin-top:7px}
.thumb{width:150px;height:96px;border-radius:11px;overflow:hidden;background:#061019;border:1px solid #244557;display:flex;align-items:center;justify-content:center;color:#698ca0;font-size:12px}.thumb img{width:100%;height:100%;object-fit:cover}.badge{display:inline-block;border:1px solid #3e6a82;border-radius:999px;padding:3px 8px;margin-right:5px}.warning{color:#e8b88c;font-size:12px;margin-top:7px}
button{border:1px solid #4f809b;background:#10415a;color:#fff;border-radius:10px;padding:9px 13px;cursor:pointer}button:disabled{opacity:.5}.cancel{background:#4b2730;border-color:#8a5663}.preview{margin-top:8px;color:#c7dfeb;font-size:13px;white-space:pre-wrap;margin-left:166px}.progress-wrap{margin-top:10px}.progress-line{display:flex;justify-content:space-between;gap:10px;color:#9fc7da;font-size:12px;margin-bottom:5px}.progress-extra{color:#789fb3;font-size:12px;margin-top:5px}.progress-track{height:8px;border-radius:999px;background:#061019;border:1px solid #244557;overflow:hidden}.progress-bar{height:100%;width:0;background:#3d819f;transition:width .25s ease}
@media(max-width:700px){.row{grid-template-columns:100px 1fr}.thumb{width:100px;height:72px}.actions{grid-column:2}.preview{margin-left:116px}}
</style></head><body><main><h1>Character Reference Lab</h1><div class="note">参考動画 → 日本語ASR。素材はreference-onlyで、ゆらへ直接コピーしません。</div>
<div class="toolbar"><button id="refresh">再読込</button><button id="all">未処理を順番に解析</button></div><div id="status" class="status"></div><div id="list"></div>
<script>
const $=id=>document.getElementById(id);let items=[];const jobs=new Map();const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]));
const stages={queued:'待機',starting:'開始',downloading_video:'動画を取得中',video_downloaded:'動画取得完了',extracting_audio:'音声を抽出中',audio_extracted:'音声抽出完了',checking_duplicate:'重複解析を確認中',preparing_asr:'ASRを準備中',transcribing:'日本語ASR処理中',saving_transcript:'解析結果をDriveへ保存中',finalizing:'最終状態を保存中',completed:'完了',failed:'失敗',canceled:'キャンセル済み',skipped_duplicate:'解析済みのためスキップ',recovered_completed:'保存済み結果から復旧',retry_required:'再試行が必要'};
function bytes(v){if(v==null)return 'サイズ: —';let n=Number(v),u=['B','KB','MB','GB'],i=0;while(n>=1024&&i<3){n/=1024;i++}return `サイズ: ${n.toFixed(i&&n<100?1:0)} ${u[i]}`}
function duration(v){if(v==null)return '長さ: —';let t=Math.max(0,Math.round(Number(v))),m=Math.floor(t/60),s=t%60;return `長さ: ${m}:${String(s).padStart(2,'0')}`}
function elapsed(v){let t=Math.max(0,Number(v)||0),m=Math.floor(t/60),s=Math.floor(t%60);return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`}
async function jsonFetch(url,options){const r=await fetch(url,options),text=await r.text();let p;try{p=text?JSON.parse(text):{}}catch{throw new Error(`HTTP ${r.status}: ${text.slice(0,240)}`)}if(r.status===401){location.reload();throw new Error('session expired')}if(!r.ok)throw new Error(p.detail||`HTTP ${r.status}`);return p}
async function load(){ $('status').textContent='読込中…';items=await jsonFetch('/api/references');jobs.clear();for(const x of items)if(x.analysis_job)jobs.set(x.reference_id,x.analysis_job);try{render()}catch(e){throw new Error(`UI render: ${e.name||'Error'}: ${e.message}`)}$('status').textContent=`${items.length}件`;}
function thumb(x){const q=encodeURIComponent(String(x.reference_id));return `<div class="thumb"><img src="/api/thumbnail?reference_id=${q}" alt="" loading="lazy" onerror="this.parentElement.textContent='No preview'"></div>`}
function progress(x){const j=jobs.get(x.reference_id);if(!j)return '';return `<div class="progress-wrap"><div class="progress-line"><span>${esc(stages[j.stage]||j.stage)}</span><span>${Number(j.percent)||0}%</span></div><div class="progress-track"><div class="progress-bar" style="width:${Number(j.percent)||0}%"></div></div><div class="progress-extra">経過 ${elapsed(j.elapsed_seconds)} ・ ${esc(j.model||'')}</div></div>`}
function result(x){const j=jobs.get(x.reference_id);if(!j)return '';if(j.error)return esc(j.error);if(j.transcript_preview)return `${esc(j.outcome||'')} / segments=${Number(j.segment_count)||0}\n${esc(j.transcript_preview)}`;return esc(j.outcome||'')}
function render(){ $('list').innerHTML=items.map((x,i)=>{const j=jobs.get(x.reference_id),active=j&&['queued','running'].includes(j.state),warning=x.manifest_error?`<div class="warning">manifest: ${esc(x.manifest_error)}</div>`:'';return `<div class="card"><div class="row">${thumb(x)}<div><div class="name">${esc(x.display_name)}</div><div class="details"><span>${duration(x.duration_seconds)}</span><span>${bytes(x.size_bytes)}</span></div><div class="meta"><span class="badge">ASR: ${esc(x.asr_status)}</span><span class="badge">audio: ${esc(x.audio_analysis_status)}</span><span class="badge">visual: ${esc(x.visual_analysis_status)}</span></div>${warning}${progress(x)}</div><div class="actions"><button onclick="run(${i})" ${active?'disabled':''}>解析</button><button class="cancel" onclick="cancelJob(${i})" ${active?'':'hidden'}>キャンセル</button></div></div><div class="preview">${result(x)}</div></div>`}).join('')}
function update(i,j){jobs.set(items[i].reference_id,j);render()}
async function poll(i,id){while(true){const j=await jsonFetch(`/api/analyze/progress/${encodeURIComponent(id)}`);update(i,j);if(!['queued','running'].includes(j.state)){await load();return j}await new Promise(ok=>setTimeout(ok,1000))}}
async function run(i){const x=items[i],retry=x.asr_status==='failed';$('status').textContent=`解析開始: ${x.display_name}`;const j=await jsonFetch('/api/analyze/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({reference_id:x.reference_id,retry})});update(i,j);const done=await poll(i,j.job_id);$('status').textContent=done.state==='failed'?`失敗: ${x.display_name}`:done.state==='canceled'?`キャンセル: ${x.display_name}`:`完了: ${x.display_name}`;return done}
async function cancelJob(i){const j=jobs.get(items[i].reference_id);if(!j)return;update(i,await jsonFetch(`/api/analyze/cancel/${encodeURIComponent(j.job_id)}`,{method:'POST'}))}
$('refresh').onclick=()=>load().catch(e=>$('status').textContent=`失敗: ${e.message}`);$('all').onclick=async()=>{ $('all').disabled=true;try{for(let i=0;i<items.length;i++)if(['pending','failed','interrupted'].includes(items[i].asr_status))await run(i);$('status').textContent='未処理の解析が完了しました'}catch(e){$('status').textContent=`失敗: ${e.message}`}finally{$('all').disabled=false}};load().catch(e=>$('status').textContent=`初期化失敗: ${e.message}`);
</script></main></body></html>
"""


app = create_app()

__all__ = [
    "AnalyzeRequest",
    "AnalysisJob",
    "CharacterReferenceLabService",
    "LabSettings",
    "app",
    "create_app",
]
