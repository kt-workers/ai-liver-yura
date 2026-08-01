# Streaming旧path互換整理 v1.0.0

## 1. 目的と結論

ロードマップG5として、G1〜G4で生じた旧Adapter pathを監査し、repository内部の通常利用を
Subsystem正規pathへ統一した。旧Streaming構造の全面削除は行わず、H〜Jの実利用がある
Runtime／Admin／Session／Comment境界と、Kまで維持するpackage-level互換だけを残す。

import方向は次の一方向に固定する。

```text
旧Core package-level export
  -> subsystems.streaming.adapters

subsystems.streaming
  -X-> app.adapters / app.bootstrap / app.plugins / app.ports
```

## 2. 削除した旧path

次の個別module wrapperはrepository内の通常利用を正規pathへ更新したため削除した。

| 削除path | 正規path |
| --- | --- |
| `app.adapters.youtube.google_youtube_auth_service` | `subsystems.streaming.adapters.youtube.oauth` |
| `app.adapters.youtube.google_youtube_client_factory` | `subsystems.streaming.adapters.youtube.client` |
| `app.adapters.youtube.google_youtube_live_chat_adapter` | `subsystems.streaming.adapters.youtube.live_chat` |
| `app.adapters.youtube.google_youtube_preparation_adapter` | `subsystems.streaming.adapters.youtube.google_youtube` |
| `app.adapters.youtube.google_youtube_streaming_control_adapter` | `subsystems.streaming.adapters.youtube.control` |
| `app.adapters.youtube.models` | `subsystems.streaming.adapters.youtube.mapper` |
| `app.adapters.youtube.youtube_api_error_mapper` | `subsystems.streaming.adapters.youtube.errors` |
| `app.adapters.obs.models` | `subsystems.streaming.adapters.obs.contracts` |
| `app.adapters.obs.obs_error_mapper` | `subsystems.streaming.adapters.obs.errors` |
| `app.adapters.obs.obs_status_mapper` | `subsystems.streaming.adapters.obs.mapper` |
| `app.adapters.obs.obs_websocket_client_factory` | `subsystems.streaming.adapters.obs.client` |
| `app.adapters.obs.obs_websocket_preparation_adapter` | `subsystems.streaming.adapters.obs.obs_websocket` |
| `app.adapters.obs.obs_websocket_streaming_control_adapter` | `subsystems.streaming.adapters.obs.control` |

削除pathはimport失敗を契約テストで固定し、同名wrapperの再追加を防ぐ。

## 3. 残す旧pathと利用者

| 残すpath | repository内利用者／理由 | 削除予定 |
| --- | --- | --- |
| `app.adapters.youtube` | package-level外部互換とsymbol identity testだけ。実装・SDK初期化なし | K |
| `app.adapters.obs` | package-level外部互換とsymbol identity testだけ。実装・SDK初期化なし | K |
| `app.adapters.streaming`のSession／Comment wrapper | Hで移動済みのSubsystem repositoryへの一段re-export。旧Runtime用 | K |
| `app.plugins.youtube_streaming` | Hで移動済みのDomain／Applicationへの一段re-exportとJまでのservice facade | K |
| `app.ports.streaming_*`、`app.ports.youtube_*`、`app.ports.comment_*` | Hで移動済みのSubsystem Portへの一段re-export | K |
| `app.bootstrap.streaming_runtime` | Admin、bootstrap export、runtime factory、互換テストが利用 | H／I／J、残余はK |
| `app.bootstrap.streaming` | Adminと旧Streaming composition／テストが利用 | I／J、残余はK |
| `app.runtime.runtime_factory`のStreaming export | 既存Core call site互換 | J／K |
| `app.config.streaming_compat` | 旧`AppConfig`からSubsystem DTOへの一方向変換を検証 | H〜J後、K |

過去の設計監査文書に記録された旧pathは履歴であり、実行時利用として数えない。

## 4. 互換面の制約

- 通常のAdapter／RuntimeテストはSubsystem正規pathを使用する
- 旧YouTube／OBS packageを利用できるのは互換identity／境界テストだけとする
- YouTube／OBS package wrapperはimport、`__all__`、canonical lazy exportのaliasだけを持つ
- wrapper importではGoogle／OBS SDK、Secret解決、network、Core Runtimeを起動しない
- Subsystemから旧Core pathをimportしない
- Core内の旧bootstrap importはAdmin、bootstrap export、runtime factoryの5組だけをbaselineとする
- `app/config/streaming_compat.py`はSecret値を保持せず、逆変換を追加しない

## 5. K工程の削除候補

- `app.adapters.youtube`、`app.adapters.obs` package-level互換
- H後に残る`app.adapters.streaming`の旧Streaming専用実装／export
- `app.plugins.youtube_streaming/**`
- Streaming専用`app.ports.streaming_*`／`app.ports.youtube_*`
- `app.bootstrap.streaming.py`、`app.bootstrap.streaming_runtime.py`
- `app.runtime.runtime_factory`のStreaming互換export
- `app.config.streaming_compat.py`と旧Core Streaming Config
- 旧Plugin registration／Capabilityの二重管理
- G5で追加したlegacy baseline／互換identityテスト

## 6. 次工程

H完了後の進捗は12/15である。次はIとしてStreaming AdminをSubsystem APIへ接続する。
Jまでは旧Runtime compositionを薄い互換facadeとして維持し、Kでwrapperと共に削除する。
