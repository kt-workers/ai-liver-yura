# Streaming Subsystemプロセス外枠 v1.0.0

## 1. 目的

Streaming公開通信契約を利用し、Coreなしで構築・起動・状態確認できる最小のStreaming Subsystemプロセス外枠を定義する。

本工程では実配信機能を移動せず、Application API、Service、内部状態、Fake Runtime、composition root、one-shot entrypoint、Event queueだけを追加する。

## 2. プロセス境界

`subsystems/streaming/`はCore Runtime、旧Streaming Plugin、Core Adapter、Admin／GUI具象をimportしない。`app`側で利用するのは`app.integrations.streaming`の公開DTOだけとする。

CoreとSubsystemは独立してimport・起動できる。今回はCore RuntimeへSubsystem Clientを配線しない。

## 3. package責務

- `api/`: transport非依存のApplication facade
- `application/`: use case調停とRuntime Port
- `domain/`: Fake外にも引き継げる最小状態遷移規則
- `adapters/`: 外部I/Oを行わない決定的Fake Runtime
- `bootstrap/`: Subsystem内部のcomposition rootとrunner
- `contracts/`: 将来の外部schema方針

Subsystem内部で公開DTOを複製しない。

## 4. lifecycle

Fakeは`IDLE`から開始し、最小の同期的遷移だけを提供する。

```text
IDLE --prepare--> READY
READY --start--> LIVE
LIVE --stop--> ENDED
READY／LIVE --emergency_stop--> ENDED
ENDED --prepare--> READY
```

許可されない操作は例外ではなく、`accepted=False`と`CONFLICT` errorを持つ公開Operation resultとして返す。

## 5. Health／Status／Capability

- status: Fake内部状態を公開`StreamingStatus`で返す
- health: 常に外部I/Oなしで評価し、注入clockのtimezone-aware timestampを使う
- capability: `PREPARE`、`START`、`STOP`、`PUBLISH_STATUS`の固定集合

Fakeは実サービスの可用性を模倣するものではなく、プロセス境界と契約利用を検証するためだけに用いる。

## 6. idempotency

- keyなしのOperationは毎回評価する
- 同一key、同一operation type、同一payloadの再送は最初のresultを返し、Eventを重複生成しない
- 同一keyを異なるoperation typeまたはpayloadで再利用した場合は`CONFLICT`
- 保存先はFake instance内memoryに限定し、複数のcomposition root間で共有しない

## 7. Event外枠

受理したOperationごとに状態変更EventとOperation完了Eventをin-memory queueへ追加する。不正操作はError Eventを追加する。

- `sequence`はFake instance内で1から単調増加する
- `cursor`は各Eventに対応する不透明値である
- `read_events(None)`は保持中の全Eventを返す
- 既知cursor指定時は、そのEventより後を返す
- 未知cursor指定時は安全側で空を返す
- readは非破壊であり、ack／削除／永続化は行わない

## 8. entrypoint

`python -m subsystems.streaming --check`でcomposition rootを構築し、status、health、API versionを一行表示して正常終了する。import時には起動せず、常駐loopやserverを持たない。

## 9. 対象外

- HTTP、WebSocket、SSE、IPC、broker
- 実network、sleep、DB、Secret、Config
- YouTube、OBS、OAuth、Live Chat、コメント取得
- 配信Session、Run of Show、永続化
- Streaming Admin接続変更
- Core Integration、Runtime配線
- 旧Streaming Pluginの移動・削除

次工程Gで実処理を移動する際も、Application APIと公開契約を維持し、Fakeを具象Adapterへ段階的に差し替える。
