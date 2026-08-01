# サブシステム分離ロードマップ v1.0.0

## 1. 方針

- 基準ブランチ: `feature/plugin-separation-development`
- 基準コミット: `6be72c695389bcf6c4dde79c8aa4f851b1316d59`
- すべての実装PRは、その時点の最新`feature/plugin-separation-development`から分岐する
- PR Baseは`feature/plugin-separation-development`
- 1 PRにつき一つのrollback可能な責務単位とする
- `develop`へ直接入れない
- 各PRは関連テスト、全体テスト、Ruff、`git diff --check`成功までDraftを維持する
- StreamingとGameをCore Pluginとして完成させない
- Streaming／Game Subsystemの未導入を正常状態として扱う

## 2. 全体順序

```text
完了: Streaming Composition Root抽出（PR #97）
  -> 完了: A. 方針文書更新
    -> 完了: B. Games／しりとり削除監査
      -> 完了: C. しりとり・旧Games Plugin削除
        -> D. Game Subsystem契約の外枠
          -> E. Streaming公開通信契約
            -> F. Streaming Subsystemプロセス外枠
              -> G. YouTube／OBS処理をSubsystemへ移動
                -> H. コメント／配信セッションをSubsystemへ移動
                  -> I. Streaming Admin接続先変更
                    -> J. Core側Integrationへ置換
                      -> K. 互換層と旧Plugin構造削除
```

## 3. A: サブシステム設計方針の確定

### 目的

StreamingをCore PluginとしてFactory化する従来ロードマップを廃止し、Streaming／Gameを独立Subsystem、Core側を薄いIntegrationとして再定義する。

### 変更

- `subsystem_architecture_policy_v1.0.0.md`
- `subsystem_migration_roadmap_v1.0.0.md`

### 完了条件

- Streaming Plugin Factory化を今後の目標にしない
- しりとり削除が明記される
- Game Subsystemは外枠のみと明記される
- 旧文書は履歴として残し、新文書の優先順位が明記される

## 4. B: Games／しりとり削除監査

### 目的

既存Games Pluginとしりとりが、どのファイル、Config、Runtime、Activity、入力処理、テストへ影響しているかを確定する。

### 調査対象

- `app/plugins/games/**`
- `app/bootstrap/runtime_plugin_setup.py`
- `app/bootstrap/runtime.py`
- `app/runtime/**`のGames参照
- Config、schema、environment override
- ActivityDefinition、matcher、ongoing input、turn handoff
- tests、fixture、docs、sample
- dependency boundary baseline

### 成果物

- Games／しりとり削除監査
- ファイル単位分類表
- 削除PR分割案
- Core-only回帰テスト一覧

### 完了条件

各対象を次のいずれかに分類する。

1. しりとり固有で削除
2. 旧Games Plugin専用で削除
3. Core汎用で維持
4. 新Game Integration契約として後で新規作成

既存コードを分類4へ安易に流用しない。

## 5. C: しりとり・旧Games Plugin削除

### 目的

製品要件でないしりとりと、それを保持するための旧Games Pluginを削除する。

Core Runtime／Configからの登録・設定依存はPR #100で削除済みである。本工程で`app/plugins/games/**`と専用テストを物理削除し、Gamesをfixtureとしていた汎用Pluginテストはテスト専用Pluginへ置換した。

### 分割原則

削除規模が大きい場合は次に分ける。

1. Runtime登録・Config・Activity露出の停止
2. しりとりDomain／Application／Adapter削除
3. 残存互換コード、テスト、文書削除

### 完了条件

- `app.plugins.games`を物理的に除外してCore importが成功する
- Games設定なしでConfigを読み込める
- Plugin ManagerへGamesを登録しない
- Games／しりとり専用Activityが露出しない
- ゲーム開始表現は通常会話へフォールバックする
- 自律活動、会話、感情、記憶が回帰しない
- dependency boundary baselineからGames負債を削除する

## 6. D: Game Subsystem契約の外枠

> 実施状況（2026-07-30）: 完了。旧Games Pluginを再利用せず、中立DTO、Gateway Protocol、Null Gateway、境界テストを追加した。

### 目的

ゲーム実装を追加せず、将来の独立Subsystem接続に必要な最小契約だけを用意する。

### 追加範囲

```text
app/integrations/games/
  __init__.py
  contracts.py
  events.py
  gateway.py
  null_gateway.py

subsystems/games/
  README.md
  contracts/README.md
```

### 契約

- disconnected／unavailable／ready／busy／degraded status
- status／snapshot query
- start／input／pause／resume／stop／reset command
- status changed／session started／output available／session ended／error event
- transport非依存の汎用payload

### 対象外

- HTTPサーバー
- DB
- ゲームルール
- しりとり
- NPC
- 実ゲーム一覧

### 完了条件

- Null Gatewayが未接続を正常状態として返す
- Core起動時にGame Subsystem接続を要求しない
- 契約がCore Runtime具象、個別ゲーム型をimportしない
- 旧Games Plugin、しりとり、Games専用Capability／Configを復元しない

## 7. E: Streaming公開通信契約

> 実施状況（2026-07-31）: 完了。公開DTO、versioning、互換方針、契約境界テストを追加した。

### 目的

Core、Streaming Subsystem、Streaming Admin間のプロセス境界契約を確定する。

### 契約対象

- 正規化StreamingStatus
- StreamingHealth
- StreamingCapability
- Comment DTO
- Operation request／result
- Event envelope
- API version
- error code
- cursor／idempotency key

### 完了条件

- YouTube／OBS固有型を公開契約に含めない
- Command／QueryとEventを分離する
- schemaの後方互換方針を定義する
- Core、Subsystem、Adminが同じ公開schemaを検証できる
- 公開契約がtransport、Core Runtime、Streaming Plugin、Adapter、Admin具象へ依存しない

## 8. F: Streaming Subsystemプロセス外枠

> 実施状況（2026-07-31）: 完了。Core非依存のApplication API、Fake Runtime、composition root、one-shot entrypoint、境界テストを追加した。

### 目的

既存処理をまだ移動せず、独立起動可能なSubsystem entrypoint、Health、Status、Event配信の外枠を作る。

### 初期配置

```text
subsystems/streaming/
  __main__.py
  api/
  application/
  domain/
  adapters/
  bootstrap/
  contracts/
```

### 完了条件

- CoreなしでSubsystemのHealth／Status確認を実行できる
- SubsystemなしでCoreを起動できる
- 接続確認用のFake implementationだけで契約テストが通る
- Python 3.10.5を使用する
- Runtime、実network、旧Streaming Pluginへ依存しない

## 9. G: YouTube／OBS処理をSubsystemへ移動

> 実施状況（2026-08-01）: 完了。G1 YouTube、G2 OBS、G3 TTS／Avatar Health抽象化、G4 Config／Secret最終移動、G5 旧path互換整理を完了した。

### 目的

YouTube API、OAuth、Live Chat、OBS WebSocket、外部I/O構築をCore側packageからSubsystemへ移す。

### 順序

1. YouTube bundle移動
2. OBS bundle移動
3. TTS／Avatar Health参照のSubsystem向け抽象化
4. Config／Secret移動
5. 旧pathの一方向互換re-export

### 分割進捗

- G1 YouTube bundle移動: 完了
- G2 OBS bundle移動: 完了
- G3 TTS／Avatar Health抽象化: 完了
- G4 Config／Secret最終移動: 完了
- G5 旧path互換整理: 完了

### 完了条件

- Core packageがYouTube／OBS SDKをimportしない
- Core ConfigがYouTube OAuth／OBS接続設定を持たない
- Adapter選択と既存挙動がSubsystem内部で維持される
- Fake／Google YouTube、Fake／Disabled／WebSocket OBSの回帰テストが通る

## 10. H: 配信セッション・コメント機能をSubsystemへ移動

> 実施状況（2026-08-01）: 完了。正規Domain／Application／Port／Repositoryと
> compositionを`subsystems/streaming`へ移し、旧pathはK削除予定の一方向互換とした。

### 目的

Session、Preparation、Readiness、Lifecycle、Run of Show、Comment処理をStreaming Subsystemの整合性境界へ移す。

### 完了条件

- CoreがStreamPreparationRuntimeを保持しない
- CoreがRun of Show、broadcast status、OBS sceneを判断しない
- コメントは公開EventとしてCoreへ届く
- Ranking／Moderationの配信固有処理はSubsystem側にある
- Coreはコメントへ応答するかどうかだけを判断する

## 11. I: Streaming Admin接続先変更

> 実施状況（2026-08-01）: 完了。Standalone AdminのREST／SSE接続先を
> Streaming Subsystem Admin APIへ変更し、Coreを任意依存とした。

### 目的

Streaming AdminをCore Admin APIやRuntime dataclassではなくStreaming Subsystem Admin APIへ接続する。

### 完了条件

- AdminがCore Runtimeをimportしない
- AdminがSubsystem status／health／capabilityを表示する
- YouTube／OBSの詳細表示はSubsystem Admin API内で閉じる
- Core停止中でもStreaming Subsystemの運用状態を確認できる

## 12. J: Core側Streaming Integrationへ置換

### 目的

Coreに残るStreaming依存を薄いClient／Gateway／Event Mapperへ置き換える。

### 追加範囲

```text
app/integrations/streaming/
  client.py
  gateway.py
  dto.py
  event_mapper.py
  connection_state.py
```

### 完了条件

- Coreは正規化状態とコメントEventだけを受け取る
- CoreからYouTube／OBSを直接操作しない
- Subsystem未接続時もCoreが正常動作する
- 接続断を通常の外部依存劣化として扱う

## 13. K: 互換層と旧Plugin構造削除

### 目的

移行完了後に、旧Streaming Plugin構造、global Ports、re-export、migration baselineを削除する。

### 削除候補

- `app/plugins/youtube_streaming/**`
- Streaming専用`app/ports/**`
- Core側YouTube／OBS／Streaming Adapter path
- `app/bootstrap/streaming.py`
- `app/bootstrap/streaming_runtime.py`
- `app.runtime.runtime_factory`のStreaming互換export
- StreamingのPlugin registration／Capability二重管理

### 完了条件

- Core-only importテストでStreaming／YouTube／OBS packageをblockして成功する
- migration baselineからStreaming具体importが0件になる
- 旧path利用がrepository内に存在しない
- 全体テストとSubsystem契約テストが成功する

## 14. ブランチ例

```text
feature/plugin-separation-development
├─ docs/subsystem-architecture-redesign
├─ audit/remove-legacy-games
├─ refactor/disable-legacy-games-registration
├─ refactor/remove-legacy-games-plugin
├─ feature/game-subsystem-contract
├─ feature/streaming-public-contract
├─ feature/streaming-subsystem-process-shell
├─ refactor/move-youtube-to-streaming-subsystem
├─ refactor/move-obs-to-streaming-subsystem
├─ refactor/move-streaming-session-to-subsystem
├─ refactor/connect-streaming-admin-to-subsystem
├─ refactor/add-core-streaming-integration
└─ refactor/remove-legacy-streaming-plugin
```

## 15. 次の作業

全15工程のうちA〜Iの13工程が完了した。残りはJ、Kの2工程である。
次工程ではJとしてCore側Streaming IntegrationをGateway／Clientへ置換する。
