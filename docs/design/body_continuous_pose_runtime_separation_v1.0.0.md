# Body連続Pose Runtime 責務分離設計 v1.0.0

## 1. 目的

Emotion因果設計から得た高レベルBody Expression入力を、モデル非依存の連続`BodyPoseFrame`へ変換し、Coreの会話・Activity・Transportを肥大化させずに外部表示へ届ける。

旧`ProceduralBodyController`および`StateDrivenBodyController`に集中していた、状態解釈、注意選択、呼吸、瞬き、微動、姿勢生成、発話口形、身体制約、物理積分、3D射影、Frame生成、通信を独立責務へ分離する。

## 2. 因果境界

```text
Emotion State
  + Activity Context
  + Interaction / Expression Intention
  + temporary external constraint
  + speech presentation
        ↓
BodyExpressionInput
        ↓
continuous pose components
        ↓
BodyPoseFrame
        ↓
BodyPoseFrameOutputPort
        ↓
HTTP / future streaming adapter
```

BodyはEmotionの下流にある表現チャネルである。Body ControllerはActivity、Motivation、権限、安全性、実行成功を決定しない。

明示的な身体指示はMotion名としてControllerへ渡さず、意味解決後の`BodyExternalConstraint`として、正規化Pose軸へ一定時間だけ重ねる。

## 3. 時間スケールの分離

### 3.1 連続全身Dynamics

次の要素は目標Poseを作り、`BodyPoseIntegrator`で現在姿勢と速度から連続的に追従する。

- 視線に追従する頭部・胴体
- Emotion由来の姿勢傾向
- Activity Context由来の開放・閉鎖・前傾・後退
- 呼吸による体高変化
- 相関微動
- 対人的なうなずき・首振り傾向
- 一時外部制約

### 3.2 低遅延の反射・同期レイヤー

次の要素は全身慣性へ残留させず、積分後の表示Poseへ重ねる。

- 瞬き
- 発話口形Fallback

理由:

- 瞬きは短時間で閉眼・再開眼する反射であり、全身姿勢と同じ慣性を通すと閉眼が間に合わず、終了後も眼が閉じ気味に残る。
- 発話口形は音声に追従する必要があり、全身姿勢の遅い追従を通すと発話開始に遅延する。
- どちらもFrame表示へだけ適用し、基礎Dynamicsを変更しない。

将来Visemeや視線安定化を追加する場合も、同じ低遅延レイヤーへ置く。

## 4. 分離した責務

### 4.1 入力・状態

- `BodyExpressionInputBuilder`: Emotion、Activity Context、採用済みExpression、期限付きRequestの合成
- `LatestBodyEmotionStateStore`: Coreで確定した最新Emotionの同期保存
- `BodyAgentStateObserver`: AgentStateからEmotionだけを抽出
- `AgentStateObserverFanout`: TelemetryとBody observerへの配送
- `TimedBodyExpressionRequestStore`: 一時表現要求の期限管理

### 4.2 連続Pose部品

- `BodyTickClock`: Tick時刻、`dt`、sequence
- `BodyMotionStateProjector`: 高レベル入力から運動Snapshotへの投影
- `BodyAttentionSelector`: 注意候補の選択とdwell
- `BodyAmbientMotionGenerator`: 相関微動とambient scan
- `BodyBreathingOscillator`: 呼吸位相
- `BodyBlinkScheduler`: 瞬き発生と開閉進行
- `BodyExpressionGestureGenerator`: 対人的な頭部リズム
- `BodySpeechMouthDriver`: 発話時間と暫定口形
- `BodyExternalConstraintPlayer`: 外部制約のattack／hold／release
- `BodyGazeTargetComposer`: 眼・頭・胴体の追従目標
- `BodyPostureTargetComposer`: 姿勢目標
- `BodyPoseTargetComposer`: 高レベル目標の正規化Pose集約
- `BodyPoseIntegrator`: PoseとVelocityの時間積分
- `BodySpeechPoseOverlay`: 低遅延の発話口形
- `BodyBlinkPoseOverlay`: 低遅延の瞬き
- `BodyCanonicalPoseProjector`: Canonical Joint／BlendShape／Gazeへの射影
- `BodyPoseFrameAssembler`: `BodyPoseFrame`の組立

### 4.3 Controller

`StateDrivenBodyController`は部品の実行順と継続状態の保持だけを担当する。計算式、HTTP、環境変数、Core状態更新を持たない。

`BodyControllerComponents`が依存生成を担当し、部品単位で差し替え・単体テストできる。

### 4.4 Runtime

`StateDrivenBodyPoseRuntime`は次だけを担当する。

1. 最新Emotion、Activity Context、期限付きExpressionを取得
2. `BodyExpressionInput`を構築
3. Controllerを1Tick進める
4. `BodyPoseFrameOutputPort`へ公開
5. Tick周期と例外隔離

`tick_once()`を公開し、常駐Loopなしで統合テストできる。

### 4.5 Transport

```text
BodyPoseFrameOutputPort
  → LatestBodyPoseFrameBuffer
  → BodyPoseFrameJsonEncoder
  → BodyPoseHttpSender
  → HttpBodyPoseFrameOutput
```

- Bufferは未送信Frameを1件だけ保持する。
- 新しいFrame到着時は古い未送信Frameを破棄する。
- Controller TickはHTTP待ちで停止しない。
- JSON化、HTTP 1件送信、Worker lifecycle、統計を分ける。
- HTTP障害はOutput内部へ記録し、Coreや次Tickへ伝播させない。

## 5. Runtime選択

- `YURA_BODY_POSE_OUTPUT_URL`あり: 連続Pose Runtime
- Pose URLなし、Avatar Outputあり: 既存Compatibility `BodyRuntime`
- どちらもなし: Body Runtimeを起動しない

環境変数は`BodyRuntimeSettings`へ集約し、Output生成とRuntime選択は別Factoryが担当する。

Compatibility Runtimeの次の設定を維持する。

- expression queue limit
- max expressions per tick
- autonomous interval
- baseline refresh interval

## 6. 依存方向

```text
Domain contracts
      ↑
Runtime components and ports
      ↑
Bootstrap factories
      ↑
Application entrypoint
```

RuntimeからBootstrapをimportしない。Emotion Bridgeの正本はRuntime層に置き、BootstrapはCompositionだけを行う。

## 7. 禁止事項

- EmotionとDriveを独立したBody主原因として並列入力しない
- Character LLMにJoint角度、固定Motion名、モデルParameterを選ばせない
- Body ControllerにActivity選択、権限、安全性、実行成功判定を持たせない
- HTTP送信をController Tick内で待たない
- 瞬き・口形を全身Dynamicsへ残留させない
- Live2D／VRM固有名をDomainへ混入させない
- Bodyの実行結果なしにCharacterへ「動作を完了した」と主張させない

## 8. 後続工程

工程7では棒人形／Body Pose Labを表示・検証専用のStacked PRとして追加する。旧Labの巨大`server.py`と`app.js`をそのまま移植せず、Hub、入力Application Service、HTTP API、SSE、静的配信、Renderer、UI State、API Clientへ分ける。
