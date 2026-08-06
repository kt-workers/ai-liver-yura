# Runtime Worker Lifecycle責務分離 v1.0.0

## 1. 目的

Body Runtime再統合に先立ち、Runtime停止時のThread終了待ちとConsole標準入力待機を、本体のオーケストレーションから分離する。

Body Controller、Transport、GUIの追加によって`RuntimeHostController`や`ConsoleInputReceiver`が肥大化することを防ぐ。

## 2. 停止順序

```text
RuntimeHostController.stop()
  1. Runtime Loop停止フラグ
  2. RuntimeWorkerThreads.stop()
       ├─ Planner.stop()
       ├─ Executor.stop()
       ├─ Planner.join(timeout)
       ├─ Executor.join(timeout)
       └─ timeout診断
  3. PluginManager.shutdown_plugins()
  4. OngoingActivityCoordinator.cancel()
```

PluginはPlanner／Executorが停止した後にshutdownする。

## 3. 責務

### RuntimeHostController

- Runtime初期化
- Runtime Loop実行
- 停止処理の順序
- Plugin shutdown
- Ongoing Activity cancel

個別Threadの開始判定、stop、join、timeout診断は行わない。

### RuntimeWorkerThreads

- Planner／Executorの開始
- autonomous planning無効時のskip
- Workerへのstop通知
- join timeoutの適用
- 終了後のalive状態
- timeout Trace

Body Runtime固有のWorkerを直接追加しない。将来Worker種類が増える場合は、管理対象のCollection契約へ拡張する。

### RuntimeThreadShutdownPolicy

- join timeoutの型付き設定
- 有限値・範囲検証

既定値は30秒。各Workerに同じPolicyを適用する。

## 4. Console入力

```text
ConsoleLineReader
  ├─ Unix add_reader
  ├─ readline
  └─ 非対応環境のdaemon thread fallback

ConsoleInputReceiver
  ├─ Task lifecycle
  ├─ trim / exit / quit
  ├─ USER_TEXT Event生成
  └─ decode error診断
```

標準入力のI/O方式はReceiverへ持たせない。

### 停止時

`ConsoleInputReceiver.stop()`は入力待機Taskをcancelし、標準入力が返るまでRuntime停止を待たない。

`add_reader`利用時はfinallyでReader登録を解除する。

fallback threadはdaemonとし、Event Loop既定Executorを占有しない。Futureがcancel済みの場合は結果を配送しない。

## 5. 保持する互換性

- `ConsoleInputReceiver(input_provider=...)`によるテスト・外部注入
- `RuntimeHostController`の既存Constructor引数
- `runtime_coordinator:threads:start`
- `runtime_coordinator:threads:stopped`
- autonomous planning無効時の`threads:skipped`
- Worker停止後のPlugin shutdown

## 6. 新しい診断

Threadがtimeout後も生存する場合:

```text
runtime_coordinator:threads:shutdown_timeout
```

記録値:

- `timeout_seconds`
- `activity_planner_thread_alive`
- `activity_executor_thread_alive`

## 7. テスト

- 30秒の共有Shutdown Policy
- Planner／Executorへのstopとjoin
- timeout後の状態返却
- autonomous planning無効時に開始しない
- Worker停止後にPluginをshutdown
- 不正timeoutの拒否
- file descriptorなしでdaemon fallbackを利用
- EOFを`None`へ変換
- 入力待機中のReceiverを即時cancel
- cancel後にReceiverを再起動可能

## 8. 後続

Body RuntimeのTick TaskやTransport Workerを追加する際は、次を分離する。

- asyncio TaskのLifecycle
- OS ThreadのLifecycle
- Output Adapter内部WorkerのLifecycle

すべてを`RuntimeHostController`の条件分岐へ直接追加しない。
