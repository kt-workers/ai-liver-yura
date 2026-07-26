# 工程5 巨大コンポーネント再監査

## 1. 目的

`AgentLifeService`の主要な責務分割完了後の`develop`を基準として、残る巨大クラス・巨大関数を再監査し、工程5で安全に分割する順序を確定する。

この監査では、単純な行数だけでなく、次の観点で優先順位を決める。

- 一つのクラスまたはモジュールに異なる変更理由が集中しているか
- 外部入出力、状態遷移、計画、実行、永続化が混在しているか
- 回帰テストを追加しながら段階的に委譲できるか
- 後続工程である設定分割やComposition Root整理と責務が重複しないか

## 2. 結論

工程5の実施順序は次の通りとする。

1. `RuntimeCoordinator`
2. `ActivityManager`
3. `ActionScheduler`
4. 工程5完了判定のための再監査

`app/bootstrap/runtime.py`と`app/config/app_config.py`も巨大だが、それぞれ工程8「Composition Rootの整理」と工程6・7「型付き設定モデル・設定ファイル分割」の主対象である。工程5では先行して全面分割せず、後続工程へ送る。

## 3. 最優先: RuntimeCoordinator

対象:

```text
app/runtime/runtime_coordinator.py
```

規模:

```text
約2,100行
```

### 3.1 現在集中している責務

- 外部Eventの公開入口
- Event Filter、Prioritizer、Buffer、Queueへの受け渡し
- 会話入力ログの記録
- User Input受信時の自律発話停止・破棄・中断
- Behavior PlannerによるActivity計画
- Plugin Capabilityによる入力ルーティング
- Pending Confirmationの解決
- 明示Activityと外部Activityの実行
- Activity Planner ThreadとExecutor Threadの調停
- Ongoing Activityの継続・終了調停
- 自律計画のポーリング
- Runtimeの起動、初期化、常駐ループ、停止
- Plugin、AgentState、Activity、Memoryを含む診断Snapshot生成
- Event SubscriberとEvent Enricherの管理

### 3.2 問題

- 入力受付、計画、実行、ライフサイクル管理が一つのクラス内で相互参照している
- `publish_events()`が、入力の正規化からActivity準備、割り込み処理、Queue投入まで担当している
- User Input固有処理と一般Event処理の境界が不明瞭
- Runtimeの状態診断変更が、イベント処理中核クラスの変更になる
- 起動停止やThread調停の変更が、Behavior・Pluginルーティングへ影響しやすい
- コンストラクタ引数と保持依存が多く、責務追加のたびに肥大化する

### 3.3 分割方針

公開Facadeとして`RuntimeCoordinator`を維持し、内部委譲へ段階的に移行する。

推奨分割単位:

```text
RuntimeDiagnosticSnapshotBuilder
RuntimeEventIngress
UserInputInterruptionCoordinator
BehaviorEventRouter
PluginEventRouter
RuntimeActivityExecutor
RuntimeLifecycleController
AutonomousPlanningLoop
```

すべてを一度に作らない。既存APIとログイベント名を保ったまま、各PRで一つの変更理由だけを移動する。

### 3.4 安全な実施順序

1. `diagnostic_snapshot()`を`RuntimeDiagnosticSnapshotBuilder`へ抽出
2. 会話入力ログ記録を専用Recorderへ抽出
3. User Input受信時の自律処理中断を`UserInputInterruptionCoordinator`へ抽出
4. Behavior・Pluginルーティングを専用Routerへ分離
5. 明示Activity・外部Activityの実行を`RuntimeActivityExecutor`へ分離
6. Event FilterからQueue投入までを`RuntimeEventIngress`へ整理
7. 起動、初期化、常駐ループ、停止を`RuntimeLifecycleController`へ分離
8. 自律計画ポーリングを専用Loopへ分離

最初に診断Snapshotを選ぶ理由は、読み取り専用処理であり、RuntimeのEvent順序やActivity遷移を変更せずに委譲境界を導入できるためである。

## 4. 第2優先: ActivityManager

対象:

```text
app/runtime/activity_manager.py
```

規模:

```text
約1,060行
```

### 4.1 現在集中している責務

- Activityの正規状態保持
- Foreground、Pending、Suspendedの遷移
- Activity Turn数と完了予約の管理
- Plugin Activity登録
- Ongoing Activityの開始・更新・終了・履歴管理
- Ongoing Turnと段階別実行結果の関連付け
- Autonomous Activityの遅延・破棄・再開
- Activity Policyの適用
- Thread間共有状態のロック
- Activity・Turn・Output結果の記録

### 4.2 問題

- 単発Activityと複数TurnのOngoing Activityが同じ状態ストアに混在する
- ActivityライフサイクルとTurn結果Repositoryの責務が混在する
- ほぼすべての処理が同じ`RLock`を使用し、分離可能な状態境界が見えにくい
- Plugin、Autonomous Talk、User Conversation固有の遷移が集約されている

### 4.3 分割候補

```text
ActivityStateStore
ActivityLifecycleManager
OngoingActivityLifecycle
ActivityTurnResultRepository
DeferredAutonomousActivityQueue
```

最初の候補は`ActivityTurnResultRepository`または`OngoingActivityLifecycle`とする。状態遷移順序とロック範囲を明示するテストを先に追加する。

## 5. 第3優先: ActionScheduler

対象:

```text
app/runtime/action_scheduler.py
```

規模:

```text
約680行
```

### 5.1 現在集中している責務

- Actionの事前準備
- Activity Policyによる出力可否判定
- 緊急停止と実行中Taskのキャンセル
- 未開始音声Segmentのキャンセル
- Resource単位の非同期Lock
- 出力優先度Queue
- 字幕・表情・音声の同期順序
- ActionExecutionResultとActivityOutputResultの生成
- 出力結果のTrace記録

### 5.2 問題

- スケジューリング、排他制御、キャンセル、結果生成が一体化している
- 同期音声出力の詳細と一般Action実行が同じクラスにある
- 結果生成とTraceが実行制御へ埋め込まれている

### 5.3 分割候補

```text
ActionExecutionPolicy
OutputPriorityGate
SynchronizedOutputExecutor
ActionResultFactory
OutputCancellationState
```

`_PriorityOutputGate`など既に存在する内部部品を、明示的な依存として段階的に昇格させる。

## 6. 後続工程へ送る対象

### 6.1 app/bootstrap/runtime.py

規模:

```text
約1,640行
```

多数のAdapter、Memory、LLM、TTS、Plugin、Runtimeを生成・接続している。巨大だが、これは主にComposition Rootの問題である。

工程5ではRuntime側の責務境界を先に安定させ、工程8で次のComposerへ分割する。

```text
core_runtime.py
llm.py
memory.py
speech.py
topic.py
plugins.py
streaming.py
application.py
```

### 6.2 app/config/app_config.py

規模:

```text
約1,100行
```

設定dataclass、YAML読み込み、型変換、デフォルト値、検証が集中している。これは工程6・7の対象とする。

型付き設定の導入済み部分を壊さず、機能別設定モデルと互換ローダーを先に分離してから設定ファイルを分割する。

## 7. 工程5の完了条件

工程5は次を満たした時点で完了とする。

- `RuntimeCoordinator`のイベント受付、ルーティング、Activity実行、ライフサイクルが独立した委譲先を持つ
- `ActivityManager`からOngoing ActivityまたはTurn結果管理の主要責務が分離される
- `ActionScheduler`から同期出力実行または結果生成の主要責務が分離される
- 公開API、Event順序、Activity遷移、ログイベント名の互換性が回帰テストで固定される
- `bootstrap/runtime.py`と`app_config.py`の課題が後続工程へ明示的に引き継がれる

## 8. 次の実装

最初の実装対象は次とする。

```text
RuntimeCoordinator.diagnostic_snapshot()
    ↓
RuntimeDiagnosticSnapshotBuilder
```

実装方針:

- Builderをコンストラクタから差し替え可能にする
- RuntimeCoordinatorの公開`diagnostic_snapshot()`は維持する
- AgentState、ActivityManager、PluginManagerから同じSnapshotを生成する
- 会話本文、秘密情報を含めない既存方針を維持する
- Snapshotのキーと値を回帰テストで固定する
