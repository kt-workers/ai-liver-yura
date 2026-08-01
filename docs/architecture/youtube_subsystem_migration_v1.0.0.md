# YouTube処理のStreaming Subsystem移行 v1.0.0

## 1. 目的

ロードマップ工程Gを責務単位で分割し、最初にYouTube API、OAuth、配信準備・状態遷移、Live Chat transportとFakeの実装所有者をStreaming Subsystemへ移す。

実装本体は`subsystems/streaming/adapters/youtube/`へ移し、旧`app` pathは移行期間中の一方向re-exportだけを保持する。公開境界は`app.integrations.streaming`の中立DTOであり、Google API response、credential、SDK例外を公開しない。

## 2. 監査結果

### 2.1 Streaming Subsystemへ移動

- `app/adapters/youtube/google_youtube_auth_service.py`
- `app/adapters/youtube/google_youtube_client_factory.py`
- `app/adapters/youtube/google_youtube_preparation_adapter.py`
- `app/adapters/youtube/google_youtube_streaming_control_adapter.py`
- `app/adapters/youtube/google_youtube_live_chat_adapter.py`
- `app/adapters/youtube/models.py`
- `app/adapters/youtube/youtube_api_error_mapper.py`
- `app/adapters/streaming/fake_youtube_preparation_adapter.py`
- `app/adapters/streaming/fake_streaming_control.py`内のYouTube Fake
- `app/adapters/streaming/fake_live_chat_adapter.py`
- YouTube固有の認証、broadcast、stream、Live Chat、errorの内部型

### 2.2 Core側に残す中立契約

- `app/integrations/streaming/**`
- `StreamingStatus`
- `StreamingHealth`
- `StreamingCapability`
- `StreamingComment`
- `StreamingOperationRequest`／`StreamingOperationResult`
- `StreamingEventEnvelope`
- `StreamingError`

Google／YouTube固有型は中立公開契約へ追加しない。

### 2.3 一時互換re-export

- `app/adapters/youtube/**`
- `app/adapters/streaming/fake_youtube_preparation_adapter.py`
- `app/adapters/streaming/fake_live_chat_adapter.py`
- `app/adapters/streaming/fake_streaming_control.py`のYouTube Fake export
- `app/ports/youtube_errors.py`
- `app/ports/youtube_live_chat.py`
- `app/plugins/youtube_streaming/domain/youtube.py`
- `app/plugins/youtube_streaming/domain/preparation.py`のYouTube DTO export

旧pathは実装を持たず、新pathへの一方向importだけとする。既存Core use caseとAdminが旧契約を利用している間の互換層であり、新規Subsystemコードから旧pathを参照しない。

### 2.4 今回対象外

- OBS AdapterとOBS Config
- 配信Session、Run of Show、Opening／Main／Closing
- Core側`PrepareStreamSessionUsecase`、Start／End use case
- Core SessionとAgentEventへ結合した旧`YouTubeLiveChatPoller`
- Streaming Admin接続変更
- Core Gateway全面置換
- 旧Streaming Plugin削除
- TTS／Avatar Health抽象化

旧Live Chat pollerは今回移動するGoogle transportを互換path経由で利用できる。Core Session／Eventから独立したpolling orchestrationへの置換は、コメント／Session移動工程で行う。

## 3. YouTube所有境界

Streaming Subsystemが所有する。

- Google OAuth scope、credential生成・refresh、token file I/O
- Google API client生成
- broadcast一覧・解決、bound stream解決
- broadcast開始／終了transition
- Live Chat API page取得
- Google responseから内部DTO／公開`StreamingComment`への変換
- Google／network例外から安定した内部errorと公開error codeへの変換
- YouTube Fakeとdisabled／unavailable Adapter

CoreはGoogle SDKを直接importせず、移行期間中は旧pathのre-exportと構造的Portだけを利用する。

## 4. OAuth／Config／Secret

YouTube設定境界を`subsystems/streaming/config/youtube.py`へ置く。既存Core Configは互換入力Adapterとして当面残し、新しいYouTube設定をCore schemaへ追加しない。

credentialとtokenは公開DTO、repr、log、Event payloadへ含めない。既存の環境変数名からpathを解決する動作、token file permission、refresh動作は維持する。Secret値やcredential fileをrepositoryへ追加しない。

## 5. Live Chat

Google Live Chat responseはSubsystem内部DTOへ変換し、公開時は`StreamingComment`へ正規化する。

- `comment_id`: message ID
- `author_id`: channel ID
- `author_display_name`: display name
- `text`: display message
- `published_at`: timezone-aware timestamp
- `stream_id`: 呼出し側が指定した不透明stream識別子
- `moderation_flags`: owner／moderator／sponsor等の中立flag
- `cursor`: Google page tokenを直接公開せず、Subsystem生成の不透明cursor

raw snippet、authorDetails、page token、Google response全体を公開DTOへ残さない。

## 6. Error正規化

YouTube内部では既存の`YouTubeApiErrorKind`を維持する。Subsystem公開結果へ変換する場合は次を基準とする。

- 認証／権限: `UNAVAILABLE`
- quota／rate limit／server／network: `EXTERNAL_DEPENDENCY_ERROR`
- timeout: `TIMEOUT`
- not found／invalid response: `INVALID_REQUEST`
- invalid state: `CONFLICT`

`HttpError`、Google Auth例外、stack trace、raw responseは公開境界を越えない。

## 7. Process Shell接続

Subsystem composition rootはYouTube設定によりFake、Google、disabledのAdapter bundleを選択する。未指定時は外部I/OのないFakeを使用する。各buildは独立instanceを生成し、Core composition rootを再利用しない。

現工程ではYouTube healthをSubsystem healthへ反映する。OBSと配信Sessionが未移動のため、実配信Operationの全面委譲は行わない。

## 8. 次のOBS工程との境界

工程Gの進捗:

- G1 YouTube bundle移動: 本工程で完了
- G2 OBS bundle移動: 未着手
- G3 TTS／Avatar Health抽象化: 未着手
- G4 Config／Secret最終移動: YouTube設定Adapterのみ。最終移動は未着手
- G5 旧path互換整理: 一方向re-exportを追加、撤去は継続

OBS移動ではYouTube bundleを変更せず、同じSubsystem composition rootへOBS bundleを追加する。
