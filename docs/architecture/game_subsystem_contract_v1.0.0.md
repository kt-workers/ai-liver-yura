# Game Subsystem契約 v1.0.0

## 1. 目的

将来、Coreとは別プロセスで動作するGame Subsystemを接続できるように、言語・通信方式に依存しない最小契約を定義する。

本契約はゲーム機能そのものではない。旧Games Pluginやしりとり実装を復元・移植せず、Coreと将来のSubsystemの境界だけを新規に定義する。

## 2. 責務境界

Coreが認識するのは次に限定する。

- Subsystemの可用性と稼働状態
- 汎用Commandの送信結果
- 汎用Event
- セッション識別子と利用者向けでない診断メッセージ

Game Subsystemが将来所有する。

- ゲームルール、ゲーム種別、盤面、ターン、勝敗
- 入力検証、NPC、タイムアウト
- ゲーム固有の永続化と外部サービス連携
- Command payloadとEvent payloadのゲーム固有schema

CoreのPlugin Manager、Capability、Config、ActivityにはGames専用の登録や分岐を追加しない。

## 3. 状態

`GameSubsystemStatus`は次を表す。

- `DISCONNECTED`: 接続設定がない、またはNull Gatewayを使用中
- `UNAVAILABLE`: 接続先は構成済みだが利用不能
- `READY`: Commandを受け付けられる
- `BUSY`: セッション処理中
- `DEGRADED`: 一部機能のみ利用可能

未導入・未接続は起動失敗ではなく、`DISCONNECTED`という正常な縮退状態として扱う。

## 4. DTO

Commandは`GameSubsystemCommand`、結果は`GameCommandResult`で表す。Command種別は`START`、`INPUT`、`PAUSE`、`RESUME`、`STOP`、`RESET`とする。

Eventは`GameSubsystemEvent`で表し、種別は`STATUS_CHANGED`、`SESSION_STARTED`、`OUTPUT_AVAILABLE`、`SESSION_ENDED`、`ERROR`とする。

Snapshotは`GameSubsystemSnapshot`で現在のstatus、active session ID、診断メッセージを返す。Command／Eventのpayloadは中立な`Mapping[str, object]`とし、Core内部型や個別ゲーム型を公開しない。

## 5. Gateway

`GameSubsystemGateway`は次の非同期操作だけを公開する。

- `get_status()`
- `get_snapshot()`
- `send_command(command)`
- `poll_events()`

通信方式、再接続、認証、serialization、Event cursorは将来の具象Adapterが所有する。Protocolは静的な構造的部分型として使用し、実行時型判定を契約要件にしない。

## 6. Null Gateway

`NullGameSubsystemGateway`はI/Oも可変状態も持たず、常に次を返す。

- status: `DISCONNECTED`
- active session ID: `None`
- message／Command拒否理由: `game_subsystem_not_connected`
- Command accepted: `False`
- Event: 空

これによりGame Subsystemが存在しなくてもCoreのimportと起動を妨げない。

## 7. 配置と接続方針

Python側の契約外枠は`app/integrations/games/`、将来の独立Subsystemの説明と外部向け契約は`subsystems/games/`に置く。

現時点では契約の利用者がないため、Runtimeやcomposition rootへGatewayを注入しない。利用者とユースケースが追加された時点で、composition rootがNullまたは具象Gatewayを選択する。

## 8. 対象外

- HTTP／WebSocket／message broker Adapter
- Runtimeへの接続
- API server、DB、認証
- ゲーム一覧、ゲームルール、NPC
- 旧Games Plugin、しりとり、互換Capability
- payloadのゲーム固有schema
