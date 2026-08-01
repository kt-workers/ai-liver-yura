# Streaming Config／Secret移行 v1.0.0

## 1. 目的

ロードマップG4として、YouTube／OBS Adapterを構築する設定とSecret参照の正本を
Streaming Subsystemへ移す。Secret値は設定DTO、YAML、公開契約へ保持せず、
`SecretProvider`からAdapter生成時にだけ解決する。

## 2. 監査結果

| 分類 | 対象 | G4での扱い |
| --- | --- | --- |
| Subsystem所有 | YouTube／OBS adapter mode、host、port、timeout、retry、poll、privacy、OAuth file参照名、OBS password参照名 | `subsystems/streaming/config/`を正本にした |
| Core汎用 | LLM、音声出力、Avatar、会話、記憶などCore本体の設定 | 変更しない |
| 外部注入 | OAuth client secret path、token cache path、OBS password | 名前だけをConfigに保持し、値は`SecretProvider`で解決する |
| 一時互換 | `app/config/streaming.py`、旧YAML schema／environment override | 既存Runtime、Admin API、production／legacy設定のため維持する |
| 一方向変換 | 旧`AppConfig`から`StreamingSubsystemConfig`への変換 | `app/config/streaming_compat.py`へ隔離した |
| 後続削除 | Core Streaming Config、旧Adapter path、旧bootstrap／Plugin構造 | G5、H、I、J、Kで利用箇所の移行後に削除する |

Core側設定を今回物理削除しない理由は、`app/bootstrap/streaming_runtime.py`、
`app/bootstrap/streaming.py`、`app/admin_api/__main__.py`および既存設定回帰テストが
まだ旧Runtimeの入力として参照しているためである。SubsystemからCoreへの逆変換や
二重同期は追加しない。

## 3. Subsystem設定境界

`StreamingSubsystemConfig`をrootとし、immutableなYouTube／OBS設定DTOを保持する。
標準ファイルは`config/subsystems/streaming.yaml`、配布用の無効構成は
`config/subsystems/streaming.example.yaml`とする。loaderは次を保証する。

- Core `AppConfig`を経由しないYAML読込
- 明示的なenvironment overrideと型変換
- 未知key、未知mode、範囲外値の拒否
- 入力pathの正規化
- YouTubeのみ、OBSのみ、両方、両方なしのdefault補完
- Fake／disabledではSecret不要、Google／WebSocket時だけ必須検証

設定エラーは設定pathと安定codeだけを公開し、入力値やSecret値をmessageへ含めない。

## 4. Secret境界

標準参照名は次の通りである。

- `STREAMING_YOUTUBE_CLIENT_SECRET_PATH`
- `STREAMING_YOUTUBE_TOKEN_PATH`
- `STREAMING_OBS_PASSWORD`

既存環境変数`YOUTUBE_CLIENT_SECRET_PATH`、`YOUTUBE_TOKEN_PATH`、
`OBS_WEBSOCKET_PASSWORD`は移行用aliasとして読む。標準名を優先し、空文字は未設定と
みなす。`EnvironmentSecretProvider`、`StaticSecretProvider`、
`NullSecretProvider`、`CompositeSecretProvider`を用意し、reprと例外には値を出さない。
OAuth credential JSON、access／refresh token、OBS password、token cache、`.env`は
repositoryへ保存しない。

## 5. 構築と依存境界

Subsystem composition rootは`StreamingSubsystemConfig`と`SecretProvider`だけで
YouTube／OBS bundleを独立構築する。TTS／Avatar dependency health providerは従来どおり
任意注入できる。設定不足はGoogle SDKまたはOBS SDKのimport前に検出し、Fake／disabled
構成ならSDKなしでSubsystemを起動できる。

Subsystem ConfigはCore Config、Core bootstrap、GUI、Admin、Game、外部SDKをimportしない。
公開Streaming DTOやHealth metadataにもcredential、token、password、Secret参照名を
含めない。

## 6. G5整理後の互換

- G5で個別YouTube／OBS module wrapperを削除し、通常利用をSubsystem正規pathへ統一した
- `app.adapters.youtube`／`app.adapters.obs`のpackage-level互換だけをKまで維持する
- `app.config.streaming_compat`は旧Runtime／Admin移行後にKで削除する

## 7. 後続工程

- H: Session／CommentをSubsystemへ移し、旧Runtimeの設定参照を減らす
- I: Streaming AdminをSubsystemへ接続し、AdminのCore Config参照を外す
- J: Coreを薄いStreaming Integrationへ置換する
- K: Core Streaming Config、互換変換、旧bootstrap／Plugin構造を削除する
