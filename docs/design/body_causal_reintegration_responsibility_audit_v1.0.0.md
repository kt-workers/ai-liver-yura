# Body因果再統合 責務監査 v1.0.0

## 1. 目的

Emotion因果エージェント設計を統合済みの`develop`を基準に、旧Body PR #159・#160・#163の成果を責務単位で再統合する。

旧PRはそのままマージしない。ファイルや関数が複数の変更理由を持つ場合は、移植前または移植と同時に責務を分離する。

## 2. 正規因果経路

```text
Perception / Event / Memory / Time
  → Meaning Appraisal
  → Affective Appraisal
  → Emotion
  → Desire / Drive / Moral
  → Motivation
  → Interaction Intention
  → Activity
  → Expression Intention
  → Body Expression
  → BodyPoseFrame
  → Live2D / 3D / Stick Mock Adapter
```

BodyはEmotionやActivityを決定しない。確定済みの心理状態・対人的意図・表現意図を身体表現へ変換する。

明示的な身体指示は主原因ではなく、通常の感情表現へ重ねる短時間の外部制約として扱う。

## 3. 旧PRの規模

### PR #159

- 54ファイル
- 6,602行追加
- Runtime停止、BodyPoseFrame契約、連続Controller、Transport、Render Lab、GUI修正が同居

### PR #160

- 18ファイル
- 3,158行追加
- Core Runtime、身体命令、参照解決、HTTP出力、棒人形GUIが同居

### PR #163

- 15ファイル
- 2,105行追加
- Emotion投影、Character表現、発話口形、姿勢合成、Runtime、HTTP出力、棒人形GUIが同居

これらは成果単位ではなく開発履歴単位にまとまっているため、そのまま統合すると責務境界が再び曖昧になる。

## 4. 現在のdevelopで先に分離した責務

`BodyActivityContextBuilder`は次を同時に担当していた。

1. Activity種別ごとの既定値
2. 複数互換位置からのInteraction Intention探索
3. Interaction Expressionの射影
4. 明示Body Context overrideの解析
5. BodyActivityContext生成
6. Trace出力

次へ分離した。

```text
BodyInteractionIntentionResolver
  └─ Activity内の互換位置から意図を復元

BodyActivityContextPolicy
  ├─ Activity種別ごとの既定値
  └─ Interaction Expressionとの合成

BodyActivityContextBuilder
  ├─ 明示overrideの適用
  ├─ 型付きBodyActivityContext生成
  └─ Trace出力
```

探索順、明示override優先、Trace項目は変更しない。

## 5. 移植前に分割する巨大Controller

旧`state_driven_body_controller.py`は約400行で、1クラスが次を担当している。

- Controller状態と時間管理
- Emotion基礎表情の算出
- Character表情名の解決
- Attack／Hold／Release envelope
- 頭・胴体・腕・姿勢の合成
- 発話口形Fallback
- BlendShape統合
- 3D射影

特に`_compose_pose()`は姿勢、表情、発話の複数レイヤーを1関数で処理しており、単独検証が難しい。

移植時は次へ分割する。

```text
BodyAffectBaselineProjector
  └─ Emotion Snapshot → 基礎表情値

BodyFacialExpressionResolver
  └─ 高レベル表現Intent → 顔ターゲット

BodyExpressionEnvelope
  └─ attack / hold / releaseの時間強度

BodyPoseExpressionComposer
  └─ 意味軸 → 頭・胴体・腕・姿勢

BodySpeechMouthDriver
  └─ 発話時計 → 口形Fallback

BodyBlendShapeMerger
  └─ 基礎・一時表情・Adapter互換値の統合

StateDrivenBodyController
  └─ 各責務を順番に呼び出す薄いオーケストレーター
```

## 6. Composition Rootの境界

`body_runtime_setup.py`は現時点では小さいが、旧PRの機能を直接追加すると次が集中する。

- 環境変数解析
- 出力Port生成
- Runtime実装選択
- Controller生成
- Compatibility経路選択
- bindとTrace

再統合時は次へ分ける。

```text
BodyRuntimeSettingsLoader
  └─ 環境変数 → 型付き設定

BodyOutputFactory
  └─ Transport設定 → Output Port

BodyRuntimeFactory
  └─ 設定とPort → Runtime

body_runtime_setup
  └─ Composition Rootとして生成・bind・Traceのみ
```

## 7. 責務別の移植方針

### Runtime停止・Lifecycle

PR #159から独立移植する。BodyドメインやGUIと同じPRへ混ぜない。

### BodyPoseFrame契約

Domain DTO、Port、Projectionを独立させる。HTTP、SSE、WebSocket、Live2D固有名を含めない。

### 感情起点のBody Expression

最新`Interaction Intention`と`InteractionExpressionProjection`を上流契約として使用する。EmotionとDriveを互いに独立した命令入力として扱わない。

### 連続Pose Controller

現在姿勢と速度を保持する純粋な時間発展へ限定する。TransportやGUIを参照しない。

### Transport

最新Frame優先、Backpressure、切断処理をPort実装へ隔離する。Body TickをI/O待ちで止めない。

### 棒人形・Body Pose Lab

Coreの判断を再実装せず、受信したBodyPoseFrameの表示と診断だけを担当する。

### Live2D／3D Adapter

Canonical BodyPoseFrameからモデル固有Parameter・Boneへの変換だけを担当する。

## 8. 分離判断基準

次のいずれかを満たした場合、機能追加前に分割する。

- 1ファイルが複数の層または変更理由を持つ
- 1関数が解析、判断、状態更新、実行、I/O、記録を複数担当する
- 一部分だけを独立してテストできない
- 条件分岐が別機能の追加ごとに増える
- 引数や戻り値に複数層の型が混在する
- Core、Body、Transport、Adapter、GUIの依存方向が逆転する

行数は補助指標とし、単一責務で説明できるかを優先する。

## 9. 工程

1. 最新developの実動作検証基盤
2. 旧Body PRの差分棚卸し
3. Runtime停止・Lifecycle分離
4. BodyPoseFrame契約分離
5. 感情起点のBody Expression生成
6. 連続Pose Controller・Transport分離
7. 棒人形／Body Pose Lab統合
8. 全体CI・実環境確認・旧PR整理

各工程は個別の変更単位とテストを持つ。明示承認なしでは`develop`へマージしない。
