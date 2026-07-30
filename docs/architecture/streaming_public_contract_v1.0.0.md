# Streaming公開通信契約 v1.0.0

## 1. 目的と所有者

本契約はStreaming Subsystemが所有し、Core、Streaming Subsystem、Streaming Adminが共有するプロセス境界である。Core側のPython参照実装は`app/integrations/streaming/`、将来の外部schema説明は`subsystems/streaming/contracts/`に置く。

公開契約は特定transportや既存Streaming Pluginの内部モデルを正本にしない。YouTube、OBS、Google API、OBS WebSocket、Admin APIの具象型を含めず、HTTP、WebSocket、IPC、in-process Fakeのいずれからも利用できる中立DTOとする。

## 2. Command／Query／Event

責務を次のように分離する。

- Query: status、health、capabilities、recent commentsを読み取る。状態変更を要求しない
- Command: `PREPARE`、`START`、`STOP`、`EMERGENCY_STOP`をOperation requestとして送る
- Event: status、health、capabilities、comment、operation結果、errorの変化をEnvelopeで通知する

Operation requestの受付可否と実行完了は分離する。`accepted=False`や通常の未接続・競合を例外だけで表現しない。

## 3. DTO

公開DTOは次で構成する。

- `StreamingStatus`
- `StreamingHealth`
- `StreamingCapability`
- `StreamingComment`
- `StreamingOperationRequest`
- `StreamingOperationResult`
- `StreamingEventEnvelope`
- `StreamingError`
- `StreamingCursor`
- `StreamingIdempotencyKey`
- `StreamingApiVersion`

Mapping payloadは初期化時にdefensive copyし、外部dictの変更やDTO経由の書き換えを防ぐ。外部SDKのraw response、例外、stack trace、認証情報を格納しない。

timestampはtimezone-awareな`datetime`で保持し、wire schemaではRFC 3339のUTC表現を使用する。ID、cursor、idempotency keyは不透明文字列であり、呼び出し側は構造解析、順序比較、外部サービスIDへの変換を行わない。

## 4. API version

現在versionは`1.0`とし、`CURRENT_STREAMING_API_VERSION`で一箇所だけ定義する。Event Envelopeは必ずversionを持つ。

- major: required fieldの削除、意味変更、既存fieldの非互換な型変更
- minor: optional field、payload key、後方互換なenum値の追加
- 同一majorは互換とみなす
- majorが異なる場合は接続前に不一致として扱う

DTOごとにversionを重複保持せず、接続negotiationとEvent Envelopeで確認する。

## 5. Error code

安定codeは`NOT_CONNECTED`、`UNAVAILABLE`、`INVALID_REQUEST`、`UNSUPPORTED_OPERATION`、`CONFLICT`、`TIMEOUT`、`EXTERNAL_DEPENDENCY_ERROR`、`INTERNAL_ERROR`とする。

未知codeは`UNKNOWN`へfallbackする。`StreamingError`はcode、利用者向けとは限らない安全なmessage、retryable、任意detailsだけを持つ。外部SDK例外やstack traceを公開しない。

## 6. Cursor

cursorはComment／Event取得位置を表す不透明値である。値がない場合は、保存済み位置を指定せずconsumer／transportの既定位置から取得することを意味する。cursorの内容解釈、大小比較、外部サービスpage tokenの直接公開を禁止する。

## 7. Idempotency key

idempotency keyはCommandの重複適用を防ぐ不透明値である。

- 同一key、同一operation、同一payloadの再送は、最初の受付・結果と意味的に同じ応答を返す
- 同一keyを異なるoperationまたはpayloadで再利用した場合は`CONFLICT`
- keyがない場合、重複排除は保証しない
- keyの保存期間と保存機構は将来のSubsystem実装が定義する

今回は保存機構を実装しない。

## 8. Schema互換方針

- 同一major内のoptional field／payload key追加を許可する
- required field削除、既存fieldの意味変更・非互換な型変更はmajorを上げる
- consumerは未知fieldを無視する
- 未知Event typeは処理せず診断記録の対象とする
- 未知statusは安全側の`DEGRADED`へ正規化する
- 未知capabilityは利用可能と判断せず無視する
- 未知error codeは`UNKNOWN`へ正規化する
- enum値を追加するproducerは、上記fallbackを前提にminorを上げる
- timestampはRFC 3339 UTC、IDは不透明文字列として扱う

## 9. 対象外

- Streaming Subsystem entrypoint、HTTP API、WebSocket、IPC
- YouTube API、OBS WebSocket、OAuth、Live Chat pollingの移動
- 配信Session、Run of Show、DB、Secret、Configの実装・移動
- Streaming Admin接続先変更
- Core RuntimeへのClient配線
- 旧Streaming Pluginの削除・Factory化
- schema serializer／decoder、idempotency保存機構
