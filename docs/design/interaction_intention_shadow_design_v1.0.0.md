# Interaction Intention Shadow設計

- Version: 1.0.0
- Status: Implemented in Phase 3 branch
- Parent roadmap: Issue #167
- Phase issue: #170
- Overall phase: 3 / 6

## 1. 目的

Motivationから「どう関わろうとしているか」を有限集合で表し、既存Internal Directiveの`response_mode`／`activity_intent`とShadow比較する。

```text
StructuredInputMeaning
Emotion / Relationship / Motivation / Target Knowledge Gap
        ↓
Interaction Intention Appraisal
        ↓
Interaction Intention（有限集合）
        ↓
既存Internal DirectiveとのShadow比較
```

Phase 3ではInteraction Intentionを行動決定へ使用しない。既存Internal Directive、Activity Plan、Character Response、Body表現を変更しない。

## 2. 有限集合

- `answer`: 質問へ答える
- `acknowledge`: 受け止める
- `listen`: 聞き続ける
- `ask`: 対象固有の不足を尋ねる
- `share`: 自分の反応・考えを共有する
- `invite`: 相手の参加や継続を促す
- `comfort`: 相手の苦痛へ寄り添う
- `set_boundary`: 境界を伝える
- `pause`: 発話せず待つ
- `act`: Activityへ向かう
- `observe`: 状況を観察する

Interaction Intentionは発話本文、具体的なPlugin選択、Capability可否、Authority、Safety判定を含まない。

## 3. 型付き契約

### 3.1 InteractionIntention

- `intention`
- `confidence`
- `source`
- `reason`
- `primary_desire`
- `target_type` / `target_id`
- `activity_type` / `operation`
- `requires_response`

`activity_type`と`operation`は入力意味から読み取れる対象だけを保持する。実行許可を意味しない。

### 3.2 InteractionIntentionComparison

- `expected`
- `directive_projection`
- `exact_match`
- `compatible`
- `comparison_stage`
- `reason`

完全一致と、意味的に許容できる互換を分ける。

## 4. 導出優先順位

### 4.1 入力意味上の義務

Motivationより先に、相手の入力が要求する関わり方を尊重する。

- `expected_response=action` → `act`
- direct answer／question → `answer`
- no response → `pause`
- closing → `acknowledge`
- acknowledgement → `listen`
- continue listening → `listen`
- acknowledgement required → `acknowledge`または`comfort`

### 4.2 Motivation

入力意味だけで決まらない場合にMotivationを使用する。

- security + 強い不快／恐れ／圧力 → `set_boundary`
- security + 弱い緊張 → `pause`
- connection + distress → `comfort`
- connection + 関係的開放性 → `invite`
- connection → `listen`
- curiosity + 対象固有Knowledge Gap → `ask`
- curiosityだけで対象不足なし → `observe`
- expression／autonomy → `share`
- achievement／recognition + Activity候補 → `act`
- 明確な方向なし → `observe`

## 5. Curiosity境界

Global Curiosityだけでは質問を許可しない。

```text
primary_desire = curiosity
AND target-specific unresolved gap exists
  → ask

primary_desire = curiosity
AND no target-specific gap
  → observe
```

これにより、好奇心が高いだけで会話を質問で占有することを防ぐ。

## 6. Internal Directiveとの比較

`InternalDirectivePlanner.plan_with_observation()`は、正規化済みInternal Directive候補とInteraction Intentionを比較する。

既存`plan()`は同メソッドを内部利用し、従来どおり`InternalDirective | None`を返す。既存呼出しの挙動は変更しない。

### 6.1 基本投影

- activity_intentあり → `act`
- answer → `answer`
- listen → `listen`
- react → `acknowledge`
- ask → `ask`
- speak → `share`
- observe → `observe`

### 6.2 内容上の補助投影

response goal、reason、requirements、forbidden claimsが明示する場合、次を優先して認識する。

- boundary／拒否／境界 → `set_boundary`
- comfort／共感／寄り添い → `comfort`
- invite／誘い → `invite`
- pause／silence／待機 → `pause`

## 7. 互換性

完全一致しなくても、次は互換として観測する。

- acknowledge ↔ listen
- ask ↔ invite
- share ↔ acknowledge
- invite ↔ ask／share
- comfort ↔ acknowledge／share
- set_boundary ↔ share／acknowledge
- pause ↔ observe／listen
- observe ↔ pause／listen

互換は正解判定ではなく、移行時の差分分類である。

## 8. Trace

```text
interaction_intention:shadow_compared
```

記録するもの:

- speech act
- primary intent
- expected response
- target identity
- Interaction Intention種別・根拠・confidence
- Directive response mode
- activity intent有無
- projected intention
- exact／compatible
- comparison stage

記録しないもの:

- Raw User Text
- Prompt
- Character Response本文
- Memory本文
- Secret

## 9. 変更しないもの

- Internal Directiveの採用結果
- question budget／initiative level
- Activity Registry検証
- Capability／Authority／Safety／Constraint
- 自律発話開始条件
- Character LLM
- Body

## 10. テスト

- direct question → answer
- action obligation → act、ただし実行許可を持たない
- acknowledgement／closing／no-response義務
- target-specific gapだけがaskを許可
- security + discomfort → set_boundary
- 既存`plan()`戻り値互換
- `plan_with_observation()`が型付き結果を返す
- Raw User TextをTraceへ複製しない

## 11. 完了条件

- 型付き有限集合が存在する
- MotivationとStructuredInputMeaningから決定論的に導出できる
- 正規化済みInternal Directive候補とShadow比較できる
- 従来`plan()`の戻り値と判断を変更しない
- TraceがRaw User Textを複製しない
- 全体pytestが成功する

## 12. 次工程

Phase 4では、Interaction Intentionを自律開始判断へ限定的に接続し、旧`DriveState.should_start_autonomous_talk()`とのShadow比較から移行する。
