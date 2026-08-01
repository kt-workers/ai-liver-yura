# サブシステム分離アーキテクチャ方針 v1.0.0

## 1. 文書情報

- 基準ブランチ: `feature/plugin-separation-development`
- 基準コミット: `6be72c695389bcf6c4dde79c8aa4f851b1316d59`
- 決定日: 2026-07-30
- 対象: Streaming、YouTube、OBS、Live Chat、Streaming Admin、Games、しりとり
- 性質: 今後の実装判断に使用する決定版

## 2. 結論

StreamingとGameは、Coreへ後付けする業務Pluginではなく、Coreの外側で独立稼働できる**サブシステム**として扱う。

Coreに置くのは、各サブシステムとの通信、状態の正規化、イベント変換だけを担う薄いIntegrationである。CoreはYouTube API、OBS WebSocket、ゲームルール、個別ゲーム状態を認識しない。

```text
Yura Core
├─ 自律活動
├─ 会話
├─ 感情
├─ 記憶
├─ 行動選択
├─ Streaming Integration ── Streaming Subsystem
└─ Game Integration ──────── Game Subsystem
```

サブシステムが停止、未導入、物理的に削除された状態でも、Coreの起動、自律活動、通常会話、感情、記憶、テキスト出力は成立しなければならない。

## 3. PluginとSubsystemの区別

### 3.1 Plugin

Pluginは、Coreの共通契約を使ってCoreの能力を拡張し、同一プロセス内でPlugin Managerにより任意登録される機能とする。

例:

- LLM Provider
- Voice Output
- Relationship Memory
- Agent Memory
- 将来の軽量な行動拡張

### 3.2 Subsystem

Subsystemは、独自の状態機械、外部I/O、認証、再接続、運用API、障害管理を持ち、Coreとはプロセス境界越しの公開契約だけで接続する独立システムとする。

例:

- Streaming Subsystem
- Game Subsystem
- 将来のAvatar／Rendering Subsystem

### 3.3 Integration

IntegrationはCore側に置く薄い接続層であり、次だけを担当する。

- Subsystem APIへの接続
- Subsystem状態をCore向け状態へ正規化
- SubsystemイベントをCore Eventへ変換
- Coreの抽象的な要求をSubsystem Commandへ変換
- 接続断、再接続、未導入状態の通知

Integrationは外部サービス固有APIを直接操作しない。

## 4. Streaming Subsystem

### 4.1 所有する責務

Streaming Subsystemは次を所有する。

- 配信セッションの準備、開始、終了、緊急停止
- YouTube OAuth、broadcast、stream、Live Chat
- OBS WebSocket、シーン、音声ソース、配信開始・停止
- YouTubeとOBSの状態整合
- Readiness、Requirements、Health、Retry、Reconnect
- Run of Show、Opening、Main、Closing
- コメント取得、Moderation、Ranking、Response候補管理
- Streaming Admin APIと運用画面
- 配信固有Config、Secret、外部SDK

### 4.2 Coreが認識する情報

Coreは次の正規化情報だけを認識する。

- 配信状態
- 配信状態の変化
- コメント受信
- 配信操作要求の受付・成功・失敗
- Subsystem接続状態
- 会話判断に必要な最小限の配信メタデータ

Coreは次を認識しない。

- YouTube broadcast ID／liveChatId／page token
- YouTube API quota、OAuth、SDK型
- OBS WebSocket、scene collection、source名
- YouTubeとOBSの開始順序
- 外部APIのretry、timeout、認証手順

### 4.3 正規化状態

```text
DISCONNECTED
UNAVAILABLE
IDLE
PREPARING
READY
STARTING
LIVE
STOPPING
ENDED
DEGRADED
ERROR
```

YouTubeとOBSの複合状態からどの正規化状態になるかはStreaming Subsystemが判断する。

### 4.4 公開契約

最初の公開契約は次の責務に限定する。

```text
Query
- get_status
- get_health
- get_capabilities
- get_recent_comments

Command
- request_prepare
- request_start
- request_stop
- request_emergency_stop

Event
- streaming.status.changed
- streaming.health.changed
- streaming.capabilities.changed
- streaming.comment.received
- streaming.operation.completed
- streaming.error.occurred
```

公開契約versionは`1.0`から開始する。Eventはversion、sequence、不透明cursorを持つ共通Envelopeで通知する。Commandは任意のidempotency keyを持ち、結果はaccepted、正規化status、安定error codeで表す。

契約はtransport非依存とし、HTTP、WebSocket、IPC、in-process Fakeのいずれでも利用可能にする。具体的な通信方式とschema serializerはSubsystem外枠工程で決定する。

### 4.5 プロセス外枠

初期外枠はCore非依存のApplication API、Service、内部状態、Fake Runtime、composition root、one-shot entrypointで構成する。

Fakeは外部I/Oを行わず、`IDLE`から準備、開始、停止、緊急停止の最小遷移、idempotency、in-memory Event queueだけを提供する。Event readはcursor指定可能な非破壊読み取りとし、brokerや永続化は後工程へ分離する。

`python -m subsystems.streaming --check`はHealth、Status、契約versionを確認して終了する。常駐server、Core Runtime配線、実Streaming処理はこの外枠へ含めない。

### 4.6 YouTube Adapter所有境界

YouTube API、OAuth、credential refresh、broadcast／stream操作、Live Chat transport、Google error mapping、YouTube FakeはStreaming Subsystem内部Adapterとして所有する。

Google responseとSDK型はSubsystem内部でYouTube固有DTOへ変換し、Subsystem外へ通知するComment、Status、Operation result、Errorは`app.integrations.streaming`の中立DTOへ正規化する。

移行期間中の旧`app.adapters.youtube`等はSubsystem実装への一方向re-exportだけを保持する。Core Configは互換入力として残すが、credential構築とGoogle SDK importをCore Runtimeの責務にしない。

### 4.7 OBS Adapter所有境界

OBS WebSocket client生成、接続確認、配信開始／停止、状態取得、Scene／Input操作、
OBS error mapping、OBS Fake／disabledはStreaming Subsystem内部Adapterとして所有する。
OBS responseとSDK例外を公開境界へ出さず、状態、Health、Capability、Operation result、
Errorは`app.integrations.streaming`の中立DTOへ正規化する。

OBS bundleはYouTube bundleと独立してfake／obs_websocket／disabledを選択する。
`obsws_python`とcredential値はreal client生成時のみ遅延loadし、旧
`app.adapters.obs`はSubsystem実装への一方向re-exportだけを保持する。Core Config
互換読込とSession配線の最終移動は後続工程とする。

### 4.8 TTS／Avatar Health境界

Streaming SubsystemはTTS／Avatarの実装を所有せず、可用性を中立なdependency health
として参照する。公開情報はkind、state、healthy、available、確認時刻、中立capability、
安全なmetadataに限定し、VOICEVOX endpoint／speaker ID、Live2D model path／Cubism
parameter、SDK型と例外を含めない。

未接続は`disconnected`を返す正常状態とする。一方のHealth Provider障害は他方から分離し、
TTS／Avatarの劣化だけでStreaming Subsystem本体をunhealthyにしない。Coreから実Healthを
供給する配線、発話Command、Avatar操作Commandは後続工程とする。

### 4.9 Config／Secret所有境界

YouTube／OBSのadapter mode、接続先、timeout、retry、poll、配信default、Secret参照名は
`subsystems/streaming/config/`を正本とする。Subsystem entrypointはCore `AppConfig`を
経由せず、専用YAMLとenvironment overrideから`StreamingSubsystemConfig`を構築する。

ConfigはSecretの値を保持せず参照名だけを保持する。OAuth client secret path、token
cache path、OBS passwordは`SecretProvider`からreal Adapter構築時にだけ解決する。
Fake／disabled構成ではSecretを要求せず、Google／OBS WebSocket構成の場合だけSDKの
load前に検証する。設定エラー、repr、公開metadataへSecret値を含めない。

移行中のCore Streaming Configは旧RuntimeとAdminの互換入力としてのみ残し、
`app/config/streaming_compat.py`によるCoreからSubsystemへの一方向変換に限定する。
逆変換と二重同期は禁止し、H〜Kで利用箇所を移した後に削除する。

### 4.10 旧path互換境界

YouTube／OBS Adapterのrepository内部参照は`subsystems.streaming.adapters`を使用する。
旧`app.adapters.youtube`／`app.adapters.obs`はKまでのpackage-level一方向re-exportに
限定し、個別module wrapper、独自factory、validation、Secret解決を置かない。

旧Plugin、Streaming Port、bootstrap、Runtime、Config変換はH〜Jの利用者が残るため、
削除工程を明示して維持する。Subsystemからこれら旧Core pathへのimportを禁止し、
wrapper import時に外部SDK、network、Secret解決、Runtime起動を発生させない。

### 4.11 Core Streaming Integration境界

Coreは`app.integrations.streaming`のGateway、Client、DTO、Event Mapperだけを使用する。
本番Clientは`/api/v1/integration/*`へHTTP接続し、テスト時だけin-process clientを許可する。
endpoint未設定時はNull Gatewayで起動し、接続断はbounded backoffで処理してCoreの他Loopを
止めない。CoreはYouTube／OBS SDK、Subsystem Domain／Application／Adapter、Admin read
model、Streaming Config／Secretをimportしない。

## 5. Game Subsystem

### 5.1 方針

現時点でゲーム機能は必要ない。個別ゲーム、ゲームエンジン、APIサーバーは実装せず、将来接続可能な外枠だけを用意する。

既存のしりとりは製品要件ではないため、サンプルや互換機能として残さず物理削除する。削除後のCoreには`app.plugins.games`、しりとり専用Activity／Intent／Command／Session／State、`games.shiritori` Capabilityを置かない。

「しりとりしよう」などの入力は専用ゲームSessionを開始せず、通常会話として処理する。将来のGame Subsystemは旧Games Pluginを移植せず、公開契約から新規設計する。

### 5.2 将来所有する責務

Game Subsystemは将来、次を所有する。

- ゲームルール
- ゲームセッション
- ターン管理
- 入力検証
- 勝敗、得点、終了条件
- タイムアウト
- NPC、対戦相手
- ゲーム固有の保存・復元
- 利用可能ゲーム一覧

### 5.3 Coreが認識する情報

Coreは次だけを認識する。

- Game Subsystemへ接続できるか
- 利用可能なゲームがあるか
- セッション状態
- 入力待ちか
- Game側が生成した発話・演出要求
- 終了結果

Coreはゲームルール、単語辞書、盤面、勝敗判定を持たない。

### 5.4 外枠の公開契約

```text
Status
- disconnected
- unavailable
- ready
- busy
- degraded

Query
- get_status
- get_snapshot

Command
- start
- input
- pause
- resume
- stop
- reset

Event
- status_changed
- session_started
- output_available
- session_ended
- error
```

Command／Eventは個別ゲーム型を含まない中立DTOとし、Gatewayはstatus、snapshot、Command送信、Event pollingだけを公開する。

外枠追加時点では、未接続を正常状態として扱うNull GatewayだけをCore側に用意する。Null GatewayはI/Oと可変状態を持たず、常に`DISCONNECTED`、`game_subsystem_not_connected`、空Eventを返す。利用者がない段階ではRuntimeへ注入せず、ゲーム実装も追加しない。

## 6. しりとり削除方針

次を一括で監査し、しりとり固有または旧Games Plugin専用であれば削除する。

- `app/plugins/games/**`
- Games Plugin Factory／registration
- Games用Configとschema
- ゲーム入力分類、Activity、turn handoff
- しりとり固有Domain、Service、dictionary、validator
- Games／しりとりのテスト、fixture、sample、README
- Core Runtime内のGames分岐

汎用に見える型でも、しりとり仕様へ依存しているものは無理に再利用しない。Game Subsystem契約は削除後に新規設計する。

削除後は次を保証する。

- Games設定がなくてもConfigを読み込める
- Games packageが物理的になくてもCoreをimportできる
- ゲーム開始表現を通常会話として処理できる
- 自律活動、通常会話、感情、記憶が回帰しない

## 7. 配置方針

初期段階では同一リポジトリ内の別プロセスとして構築する。

```text
app/
  core/
  runtime/
  bootstrap/
    runtime.py
  integrations/
    streaming/
    games/

subsystems/
  streaming/
    api/
    application/
    domain/
    adapters/
      youtube/
      obs/
    bootstrap/
    admin/
  games/
    README.md
    contracts/
```

物理的な別リポジトリ化は、公開契約と運用方法が安定した後に判断する。

## 8. 依存規則

1. Coreは`subsystems/**`をimportしない。
2. CoreはYouTube、OBS、ゲーム固有packageをimportしない。
3. SubsystemはCore Runtime／Usecase具象をimportしない。
4. IntegrationとSubsystemは共有された通信DTO／schemaだけを共有する。
5. Subsystemの停止をCoreの起動失敗にしない。
6. CoreはSubsystem固有statusをそのまま保持しない。
7. Admin画面はCoreを経由せず、所有するSubsystemのAdmin APIへ接続する。
8. Secretと外部サービスConfigは所有するSubsystemに置く。
9. Streaming Session、Run of Show、Commentの状態・policy・repositoryはStreaming
   Subsystemが所有し、Coreは公開Eventと中立content execution境界だけを扱う。
10. Streaming AdminのREST／SSE、運用read model、Streaming専用diagnosticsはStreaming
    Subsystemが所有し、Core Admin APIを経由しない。

## 9. 既存設計の扱い

次の従来方針は廃止する。

- Streaming全体を単一Core PluginとしてFactory化する
- YouTube／OBS AdapterをCore側Composition Rootで組み立て続ける
- Streaming AdminをCore Runtime dataclassへ接続する
- Games Pluginをしりとり実装の入れ物として維持する

`docs/architecture/streaming_plugin_separation_reaudit_v1.0.0.md`と
`docs/architecture/streaming_plugin_migration_roadmap_v1.0.0.md`は、方針変更前の監査記録として残す。今後の実装判断では本書と`subsystem_migration_roadmap_v1.0.0.md`を優先する。

## 10. 完了状態

最終的なCore-only状態は次を満たす。

- Streaming SubsystemとGame Subsystemを起動しなくてもCoreが正常起動する
- YouTube／OBS／Games packageを物理的に除外してもCore importが成功する
- Coreの会話、自律活動、感情、記憶、テキスト出力が動作する
- Streaming／Gameの状態は接続時だけIntegration経由でCore Eventへ流入する
- 外部サービスの変更はSubsystem内部に閉じる
