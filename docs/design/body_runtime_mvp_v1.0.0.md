# Body Runtime MVP 設計 v1.0.0

## 1. 目的

Body Subsystemのドメイン契約を、LLMを呼ばずに常時稼働する最小Runtimeへ接続する。

このMVPは独立プロセス化の前段であり、Coreと同一プロセス内でTick Loopを持つ。Activity文脈、人格的な身体表現要求、発話状態を保持し、Avatar Runtimeへ`AvatarPerformancePlan`を送る。

## 2. Runtime構成

```text
BodyActivityContext ───────┐
BodyExpressionRequest ─────┤
SpeechPresentationRequest ─┘
             ↓
        BodyRuntime
        ├─ 30fps Tick Loop
        ├─ Activity Context保持
        ├─ 優先度付き表現要求Queue
        ├─ 発話時間状態
        ├─ Activity基礎姿勢生成
        ├─ Autonomous Motion生成
        └─ 障害診断Snapshot
             ↓
     AvatarPerformancePlan
             ↓
       AvatarOutputPort
```

## 3. 更新周期

既定値は30fpsとする。設定可能範囲は1〜120fpsであり、Body Runtimeの各TickではLLMを呼び出さない。

Tick内では次の順序で処理する。

1. 発話時間の失効判定
2. Activity Context変更または定期更新時の基礎姿勢送信
3. 高レベル身体表現要求の取り出しとTrack化
4. 呼吸・微細な重心移動などの自律動作送信

## 4. Activity基礎姿勢

Activity Contextから、注意対象と姿勢傾向を長時間保持するTrackへ変換する。

- 注意対象は`attention` Track
- open / closed / forward / withdrawnは`torso` Track
- Trackは現在姿勢から開始し、終了時に他のTrackをneutralへ戻さない
- Activity Contextが変化したときと、長時間保持Trackの期限前に再送する

## 5. 明示的な身体表現

`BodyExpressionRequest`は優先度付きQueueへ入る。

`BodyExpressionPlanner`がagreement、approach、openness、surprise、assertiveness等の意味軸から、首・胴体・左右腕・注意の独立Trackへ展開する。

1 Tickで処理する要求数には上限を設け、入力集中時にAvatar Runtimeへ無制限送信しない。Queueが満杯でもCore側へ例外を返さず、診断状態へ記録する。

## 6. Autonomous Motion

Character LLMやActivityから明示要求がなくても、Body Runtimeは定期的に自律動作を生成する。

MVPでは次を実装する。

- breathing
- micro_sway

これらは低いlayer priorityを持つ加算Trackであり、人格的な表現やActivity姿勢を上書きしない。

瞬き、眼球微動、姿勢補正の詳細化は後続実装とする。

## 7. 発話状態

`SpeechPresentationRequest`を受け取ると、音声の実時間とpresentation IDをBody内部へ保持する。

MVPでは音声Transportの再生そのものはまだ行わない。発話の開始・終了をBodyの共通時計へ載せるところまでを実装し、後続でAudio Player、音素、Viseme、強調語の実時間位置を接続する。

## 8. 障害分離

Avatar出力が未接続または送信失敗しても、Body RuntimeとCoreを停止しない。

- Avatar未接続は通常の縮退状態として扱う
- 送信例外は最大240文字の診断情報へ変換する
- 次のTickと次の身体要求は継続する
- 会話本文、音声データ、秘密情報をSnapshotへ含めない

## 9. Lifecycle

`start()`と`stop()`は冪等である。

- `start()`の重複呼び出しでTaskを重複生成しない
- `stop()`は待機中Taskを取消し、安全に終了する
- Avatar Runtimeの応答を待たずに停止可能
- `tick_once()`を公開し、テストまたは将来の外部Loopからも駆動できる

## 10. 診断Snapshot

`BodyRuntimeSnapshot`は次のみを公開する。

- running
- tick_count
- active_activity_id
- pending_expression_count
- active_speech_id
- last_performance_id
- last_error

## 11. 今回の未実装

- 独立プロセス化
- IPC / WebSocket Gateway
- カメラ・音・カーソルからのPerception入力
- 注意候補の選択とデッドゾーン追従
- 実際の音声再生
- 音素 / Viseme同期
- 瞬き・眼球微動の詳細制御
- Live2D / VTube Studio固有Parameter変換
- Avatar Runtimeからの完了・中断通知

## 12. 次の移行段階

1. Composition RootでBody Runtimeを生成し、Application lifecycleへ接続する
2. Activity遷移時に`BodyActivityContext`を送るGatewayを接続する
3. Character出力から`BodyExpressionRequest`を送る
4. TTS生成結果を`SpeechPresentationRequest`へ変換する
5. 独立プロセス用Transportを追加する
6. インプロセス実装を同じ`BodySubsystemPort`のRemote Adapterへ差し替える
