# Interaction Intention Character・Body統合設計 v1.0.0

## 1. 目的

Emotionから導出されたInteraction Intentionを、Character ResponseとBody表現の共通上流原因として接続する。

```text
Emotion / Desire / Drive / Motivation
  -> Interaction Intention
  -> Interaction Expression Projection
     -> Character Response Context
     -> Body Activity Context
```

この接続は表現方向を共有するためのものであり、Activity選択、Capability、Authority、Safety、実行可否をCharacterまたはBodyへ委譲するものではない。

## 2. 非目標

- Character LLMにActivityを選ばせない
- Character LLMに実行成功を判断させない
- Bodyへユーザー入力を直接モーション命令として渡さない
- Interaction Intentionからプリセットモーション名を選ばない
- `act`意図だけを根拠に「実行した」と発話させない
- Emotion／Drive中心のBody自律生成を置き換えない

## 3. 共通契約

### 3.1 Interaction Intention

有限集合を維持する。

- answer
- acknowledge
- listen
- ask
- share
- invite
- comfort
- set_boundary
- pause
- act
- observe

`InteractionIntention.from_context()`は有限項目だけを復元し、不明な意図や不正なconfidenceを拒否する。

### 3.2 Interaction Expression Projection

Interaction Intentionを以下の高レベル表現へ決定論的に射影する。

- `EmbodiedExpressionIntent`
- `BodyAttentionIntent`
- `BodyPostureTendency`
- movement energy
- gaze freedom
- Character用content strategy

射影にはモーション名、身体部位の角度、実行権限を含めない。

```json
{
  "content_strategy": "state_boundary_calmly",
  "posture_tendency": "closed",
  "movement_energy": 0.30,
  "gaze_freedom": 0.20,
  "observation_only": true,
  "grants_execution_authority": false
}
```

## 4. 通常会話経路

`SeparatedSituationEvaluationAdapter`は、従来のActivity判断を変更せず、Shadowで導出したInteraction Intentionを結果へ添付する。

```text
StructuredInputMeaning
  -> Internal Directive candidate
  -> Validation
  -> Legacy Situation Payload
     + interaction_intention
     + interaction_expression
     + interaction_intention_comparison
```

会話Activityでは、Character Responseへ確実に保持するため次を内部制約へ格納する。

- `_interaction_intention`
- `_interaction_expression`

外部Activityの制約スキーマには追加しない。プラグイン固有constraintsと表現メタデータを混在させないためである。

## 5. 自律会話経路

Phase 4で採用された自律Interaction IntentionをEvent PayloadとMemoryの両方へ格納する。

```text
Autonomous Interaction Decision
  -> interaction_intention
  -> interaction_expression
  -> memory
  -> Character Response Context
```

これにより自律開始判断とCharacter表現が同じ意図を参照する。

## 6. Character境界

`ResponseContext`はMemoryまたは安全な内部制約からInteraction Intentionを型付きで復元する。

Character Promptへ渡る情報は以下に限定する。

- finite intention
- confidence
- response obligation
- target
- expression direction
- content strategy

Characterの実行主張は引き続き次の既存契約で制御する。

- `ActivityExecutionResult`
- allowed claims
- forbidden claims
- claim validation

`InteractionIntentionType.ACT`は実行要求・活動方向を表すだけであり、実行開始、完了、成功の証拠ではない。

## 7. Body境界

`BodyActivityContext`と`BodyExpressionRequest`は任意のInteraction Intentionを保持できる。

`BodyActivityContextBuilder`は次の順で値を決める。

1. ActivityTypeの基本身体文脈
2. Interaction Intentionの決定論的表現射影
3. 明示された`body_context` override

明示overrideを最優先する。Interaction Intentionは身体を固定ポーズへ拘束せず、姿勢傾向、注意方向、動きの活性度だけを調整する。

Bodyは引き続き次を自律的に生成する。

- 呼吸
- 瞬き
- 微細動作
- 視線の連続変化
- Emotion／Drive由来の揺らぎ
- Avatar固有の姿勢・関節への展開

## 8. 因果例

### comfort

```text
comfort
  -> gentle / warm
  -> forward posture
  -> maintain attention
  -> low movement energy
  -> Characterは決めつけず寄り添う
```

### set_boundary

```text
set_boundary
  -> guarded / assertive
  -> closed posture
  -> avoid attention tendency
  -> moderate tension
  -> Characterは落ち着いて境界を伝える
```

### act

```text
act
  -> focused expression
  -> execution authority = false
  -> CharacterはActivityExecutionResultだけを事実根拠にする
  -> Bodyはモーションコマンドを受け取らない
```

## 9. 観測性

追加Trace:

- `interaction_intention:situation_projected`
- `interaction_intention:body_context_projected`

Traceへ記録するのは有限な意図、表現方向、数値、Activity種別だけとする。

Raw User Text、Character本文、Prompt本文、Memory本文は複製しない。

## 10. 移行方針

Phase 5では共通意図を接続するが、次の旧互換境界は削除しない。

- Internal Directive
- legacy expression name
- legacy gesture
- existing Character claim validation
- Activity constraints schema

旧経路の縮小・削除はPhase 6で、観測結果と全体回帰を確認してから行う。

## 11. 検証境界

Phase 5の回帰では次を確認する。

- 型付き意図の復元にRaw User Textを使わない
- Character ContextとBody Contextが同じ意図を保持する
- 外部Activityのconstraints schemaへ内部表現情報を混入させない
- 明示`body_context`が意図射影より優先される
- `act`射影が実行権限を持たない
- 自律EventのPayloadとMemoryで意図・表現方向が一致する
- 既存Character claim validationとActivity lifecycleが維持される
- 全体pytestが成功する
