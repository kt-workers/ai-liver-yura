# SemanticUtterancePlan Adjacent Contract v1.0.0

## 位置付け

Parent #225 / Work #226 / Draft PR #231。

`SemanticUtterancePlan` / `ResponseSemanticsPlanner` のModule Unit gateがPASSした後に実施する、#226内の隣接契約ゲートを定義する。

本契約はCharacter Language Realizer (#227)、Validator (#229)、Lab (#223)、TTS、Bodyをまだ接続しない。

## 対象境界

### 1. ResponseContext入力境界

```text
Activity / Event payload
        ↓
Base ResponseContextBuilder
        ↓
InternalStateAwareResponseContextBuilder
  - Emotion source projection
  - Drive source projection
        ↓
ResponseSemanticsPlanner
        ↓
SemanticUtterancePlan
```

`InternalStateAwareResponseContextBuilder` は意味判断そのものを再実装せず、Plannerが判断できる型付き入力を決定的に供給する。

Emotion / Driveのsource precedenceは既存契約を維持する。

```text
event_payload
> activity.context
> autonomous_situation_context
```

Driveは数値かつboolではない値だけを`ResponseContext.drive`へ投影する。

### 2. Serialization / memory境界

```text
SemanticUtterancePlan
  ↓ as_context()
ResponseContext.memory["semantic_utterance_plan"]
  ↓ from_context()
SemanticUtterancePlan
```

Plan追加時に既存memoryを破壊しない。

serialized Planは発言意味契約であり、次を丸ごと複製しない。

- raw user text
- full ResponseContext
- raw Emotion / Drive numeric state
- unrelated memory payload
- Activity実装payload

`evidence_refs`はCore内部provenanceとしてPlan内に存在してよいが、raw valueそのものは持たない。

### 3. 既存discourse projectionとの境界

`project_semantic_discourse_context()` は既存の有限なrepetition contextをPlanへ付加できる。

この隣接ゲートでは、付加済み`discourse_context`がserialization round-tripで保持されることだけを確認する。

#193 Discourse Appraisalの判断規則を本Issueへコピー・再実装しない。

## 契約テスト項目

最低限、次を確認する。

1. event payload / activity context / autonomous situationに同じEmotion dimensionがある場合、event payloadが採用される
2. event payloadが無ければactivity context、それも無ければautonomous situationへ決定的にfallbackする
3. Driveはnumeric non-boolだけが投影され、bool / string / nested objectをraw Drive値として通さない
4. raw Drive数値はSemantic Planへそのまま露出しない
5. `_internal_directive`が欠落・不正な場合、internal-state target/propositionを捏造しない
6. Base Builderが生成した既存memoryを保持したまま`semantic_utterance_plan`だけを追加する
7. `as_context() → memory → from_context()`でtarget / propositions / budgets / interpersonal / discourseの意味が保持される
8. serialized Planへraw user textやunrelated memory markerが混入しない
9. repetition用の既存`discourse_context`が付与済みの場合、round-trip後も保持される

## 合否境界

このゲートで判定するのは#226の入力・搬送契約だけである。

PASS後も次は未検証として残す。

- #227 Character LLMがPlanの意味を保持して自然文へ実現できるか
- #229 Validatorが意味改変を検知できるか
- #223 Lab上の実LLM挙動
- Voice / Body表現
- `python -m app`全体結合

これらを本ゲートの合否根拠にしない。

## 実行順

```text
#226 Module Unit Test        [PASS]
        ↓
#226 Adjacent Contract Test  [current]
        ↓ PASS後に#226を一旦freeze
#227 Module Unit Test
        ↓
#226 ↔ #227 Contract Test
        ↓
後続Subsystem Integration
```
