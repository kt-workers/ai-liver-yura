# Core Streaming Integration移行監査 v1.0.0

## 目的

工程Jでは、CoreがYouTube／OBS／配信Sessionの具象を構築する旧経路を利用停止し、
`app/integrations/streaming`の公開契約だけを通じて独立Streaming Subsystemへ接続する。
公開契約はv1.0を維持し、Admin UI用read modelには依存しない。

## 変更前監査

| 旧責務・経路 | 変更前の利用 | Jの分類 | J後の扱い | Kでの扱い |
|---|---|---|---|---|
| `app.bootstrap.streaming*` | 旧Admin／互換テスト | Jで利用停止する旧path | Core起動経路から不使用 | 物理削除 |
| `app.plugins.youtube_streaming` | Domain／Application re-export | Subsystem側の責務 | Coreから不使用 | 物理削除 |
| `app.adapters.streaming` | Fake／Repository re-export | Subsystem側の責務 | Core Integrationから不使用 | 物理削除 |
| Streaming専用`app.ports` | Subsystem Port re-export | Subsystem側の責務 | Core Integrationから不使用 | 物理削除 |
| `app.admin_api` Streaming route | 旧Core Admin互換 | Core Admin専用で維持 | deprecated、GUIは利用しない | Streaming route削除 |
| `subsystems.streaming.admin_api` | Admin UI read model | Streaming Admin Subsystem側 | 維持 | 維持 |
| `subsystems.streaming.api` | 公開Application facade | Core Integrationへ置換 | 公開HTTP routeを追加 | canonical |
| `app.integrations.streaming` | 公開DTOの骨格 | Core Integrationへ置換 | Gateway／Client／Mapperを完成 | canonical |
| Character／LLM／Memory／Game | Core汎用責務 | 今回対象外 | 変更なし | 変更なし |

## 正規接続

```text
Core Runtime
  -> CoreStreamingIntegration
  -> StreamingGateway
  -> HttpStreamingClient
  -> /api/v1/integration/*
  -> StreamingSubsystemApi
```

テストでは`InProcessStreamingClient`を利用できる。本番の正規経路はHTTPであり、
CoreとSubsystemは別プロセスで起動できる。

## 公開route

| Method | Route | 公開契約 |
|---|---|---|
| GET | `/api/v1/integration/version` | API version |
| GET | `/api/v1/integration/status` | 正規化status |
| GET | `/api/v1/integration/health` | SDK非依存health |
| GET | `/api/v1/integration/capabilities` | 正規化capability |
| GET | `/api/v1/integration/dependencies/health` | dependency health |
| POST | `/api/v1/integration/operations` | operation request／result |
| GET | `/api/v1/integration/events?after=` | cursor付きevent snapshot |

Admin専用diagnostics／settings／Session read modelをCoreから利用しない。

## 接続とイベント

- endpoint未設定またはdisabledでは`NullStreamingGateway`を使い、I/OなしでCoreを起動する。
- 接続失敗は`unavailable`／`degraded`として保持し、Coreの他Loopを止めない。
- retryは0.5秒から最大8秒のbounded backoffとし、busy loopを作らない。
- cursorと最大512件のevent IDを保持し、再接続時の重複配送を抑止する。
- commentは明示されたmetadataだけを保持し、Coreへ`VIEWER`権限で渡す。
- token、credential、live chat IDなどの秘密・具象識別子はMapperで除去する。
- unknown eventはv1.0 policyどおり無視する。

## Core設定境界

Coreが参照する環境変数は次に限定する。YAMLへSecret実値は追加しない。

- `YURA_STREAMING_SUBSYSTEM_ENABLED`
- `YURA_STREAMING_SUBSYSTEM_API_URL`
- `YURA_STREAMING_SUBSYSTEM_TIMEOUT_SECONDS`
- `YURA_STREAMING_SUBSYSTEM_RECONNECT_SECONDS`
- `YURA_STREAMING_SUBSYSTEM_RECONNECT_MAX_SECONDS`
- `YURA_STREAMING_SUBSYSTEM_API_TOKEN`

YouTube OAuth、OBS password、broadcast、Run of Show、polling設定はSubsystem所有である。

## K削除確定対象

> 工程Kで以下をすべて削除済み。Coreの正規Streaming境界は本書記載のIntegrationのみである。

- `app/plugins/youtube_streaming/**`
- `app/adapters/streaming/**`、`app/adapters/youtube/**`、`app/adapters/obs/**`
- Streaming専用`app/ports/*`
- `app/bootstrap/streaming.py`、`app/bootstrap/streaming_runtime.py`
- `app.runtime.runtime_factory`のStreaming互換export
- `app/config/streaming_compat.py`と旧Core Streaming Config
- `app/admin_api`のStreaming専用route／service／console logic
- Streaming Admin GUIの旧client alias、旧env fallback、`core-event`互換
- migration allowlist／互換性維持専用テスト
