# Streaming Admin Subsystem接続移行 v1.0.0

## 1. 結論

工程IでStandalone Streaming Adminの正規接続先をCore Admin APIからStreaming
Subsystem Admin APIへ変更した。Browser向けURL shapeと画面構成は維持し、状態所有、
read model、操作、SSEは`subsystems.streaming`内で完結する。Coreは任意依存であり、停止時も
Admin APIと画面を起動できる。

```text
Browser -> Streaming Admin Web :8780
        -> Streaming Subsystem Admin API :8781
        -> StreamingSubsystemApi / Session Components
```

## 2. route監査

| 現行route | 旧所有者 | 移行後所有者／契約 | Browser利用 | 互換 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/health`、`status`、`capabilities` | Core runtime／Plugin Registry | Subsystem公開status／health／capability | bootstrap、service card | 旧Core配信routeは削除済み |
| `GET /api/v1/dependencies/health` | Core snapshot | Subsystem dependency healthとoptional Core接続状態 | console | 新規 |
| `/api/v1/youtube/auth*`、`broadcasts*` | Core composition | Subsystem YouTube preparation Port | 配信設定 | URL shape維持 |
| `/api/v1/obs/*` | Core composition | Subsystem OBS preparation Port | service card／更新 | URL shape維持 |
| `/api/v1/streaming/session*` | `StreamPreparationRuntime` | Subsystem Session Application | 配信操作／進行 | URL shape維持 |
| Run of Show／Opening／Main／End／Lifecycle | 旧Plugin service | Subsystem Domain／Application | 進行tab | URL shape維持 |
| Comment／Moderation／Ranking／Response | 旧Plugin service | Subsystem Comment Application | comment tab | URL shape維持 |
| `/api/v1/admin/console` | Core read model | Subsystem Admin projector | `/api/bootstrap` | `runtime_state`はK削除候補 |
| diagnostics／settings | Core diagnostics | Streaming専用in-memory diagnostics／安全な設定だけ | diagnostics／settings | filesystem保存はdisabled |
| `/api/v1/events` | Core broker | `StreamingEventEnvelope`のbounded replay | Browser SSE | `/events/stream`はKまでalias |

旧`app/admin_api`のrouteはJ／K回帰用として変更せず、Streaming Adminからは使用しない。

## 3. APIと認証

- factory: `create_streaming_admin_api(StreamingSubsystemApi, token=...)`
- entrypoint: `python -m subsystems.streaming.admin_api`
- default: `127.0.0.1:8781`。既存8765/8766/8770/8771/8780/8790を監査し未使用を確認した。
- token: `STREAMING_SUBSYSTEM_ADMIN_API_TOKEN`。RESTとSSEに同じBearer認証を適用する。
- error: `error.code/message/retryable/trace_id`。401／404／409／422／503を保持する。
- DTOはDomain objectを直接返さず、datetime／enumを安定JSONへ変換し、Secret・token・
  live chat参照・raw SDK responseを除外する。

## 4. Event

`GET /api/v1/events`は`StreamingEventEnvelope`をSSEへ変換し、event ID、type、timestamp、
correlation ID、payloadを返す。`Last-Event-ID`でbounded in-memory履歴から再開し、0.5秒間隔の
heartbeatでbusy loopを避ける。GUIは`streaming-event`を変更通知として受け、短時間coalesce後に
REST bootstrapを再取得する。旧`core-event`は正規名として使用しない。

## 5. 環境変数互換

正規名は次の4つで、新旧両方がある場合は新名称を優先する。

- `STREAMING_SUBSYSTEM_ADMIN_API_URL`
- `STREAMING_SUBSYSTEM_ADMIN_API_TOKEN`
- `STREAMING_SUBSYSTEM_ADMIN_API_TIMEOUT`
- `STREAMING_SUBSYSTEM_ADMIN_OPERATOR`

旧`AI_LIVER_ADMIN_*` fallbackはKで削除した。tokenはrepr、response、logへ出さない。

## 6. 後続工程

- J: 完了。Core側Streaming具象依存をGateway／Clientへ置換した。Core Integrationは
  Admin read modelではなく`/api/v1/integration/*`を使用する。
- K: 完了。旧Core Streaming route、旧client alias、旧環境変数fallback、Plugin／Port互換を削除した。
