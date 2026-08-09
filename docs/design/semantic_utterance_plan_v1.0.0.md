# SemanticUtterancePlan v1.0.0

## 目的

Character LLMへEmotion / Desire / Drive等のraw内部値を直接解釈させて「何を言うか」を決める構造から、発話内容をCharacter非依存の意味契約として先に確定する構造へ移行する。

Parent #225 / Work #226 の実装設計。

```text
StructuredInputMeaning
+ Validated InternalDirective
+ Emotion / Desire / Drive
+ Relationship
+ Activity facts
+ Memory / Situation
+ Discourse Appraisal
        ↓
ResponseSemanticsPlanner
        ↓
SemanticUtterancePlan
        ↓
Character Language Realizer (#227)
```

## Characterとの責務境界

本Planは **What to say** の正本であり、Character Profileによる言い回しを含まない。

含める:

- speech act
- typed target
- semantic proposition
- propositionの存在/強度を表すsemantic state
- certainty
- content requirement / forbidden addition
- question / new-direction budget
- self disclosure
- Relationshipの内容制御facet
- Discourse Appraisalの意味化済みfacet

含めない:

- Character固有の語尾
- 一人称
- 口癖
- 敬語の具体形
- fillerの具体語
- TTS speed / pitch / intonation
- pause ms
- Body joint / gesture preset
- raw Emotion / Drive / Relationship numeric value

## SemanticProposition

内部状態を日本語説明へ変換せず、意味として保持する。

例:

```json
{
  "kind": "self_state",
  "predicate": "joy",
  "state": "absent",
  "certainty": "high",
  "concept": null,
  "evidence_refs": ["emotion.current.reactive.joy"]
}
```

`evidence_refs`は値そのものではなく、どのstructured factを根拠に意味化したかを示す参照である。

## 数値から意味への変換

0〜1の強度dimensionはCharacterへ数値を渡さず、次の有限状態へ意味化する。

- `absent`
- `low`
- `moderate`
- `high`
- `very_high`

これは日本語台詞テンプレートではない。Character Language Realizerは後段で同じ意味をCharacter Profileに沿って自由に言語実現する。

### 例: joy=0 / curiosity高

入力:

```text
target = internal_state/joy
joy = 0.0
curiosity = 0.82
engagement = 0.78
```

Semantic Plan:

```text
predicate = joy
state = absent
```

`curiosity` / `engagement`はjoyのpropositionへ昇格しない。

これにより、Characterがraw stateを見て`curiosity`を`joy`へ意味的に代用する責務をなくす。

## Current Feeling

`current_feeling`は単一dimensionではないため、overview markerだけではなく、Emotionの`reactive` dimensionを意味化して併記する。

例:

```text
current_feeling = overview
calm = moderate
joy = absent
anger = absent
```

raw数値はPlanへ含めない。

Characterは#227でこの意味表現を自然な人物発話へ変換する。

## Desire

`current_desire`では、利用可能な場合は既存`ResponseContentPlan.primary_desire`をsemantic conceptとして使用する。

```text
predicate = current_desire
state = present
concept = connection
```

将来typed DesireStateがResponseContextへ直接搬送された場合は、そちらを正本へ昇格する。

## Relationship

Relationshipは同じraw scoreを上流とCharacterで二重解釈しない。

#226が扱う内容制御facet:

- disclosure_permission
- boundary_sensitivity
- social_distance
- current_tension

現段階では既に意味化された文字列facetだけを採用し、`trust=0.92`等のraw scoreから勝手に距離感を推測しない。

Character向けのregister / 呼称 / 冗談 / 柔らかさは#227で扱う。

## Discourse Appraisalとの境界

#193が所有するDiscourse Appraisalを再実装しない。

利用可能になった場合、以下の意味化済みfacetをPlanへ取り込める。

- topic_transition
- acknowledgement_need
- selected_topic_source
- response_obligation

## Runtime統合

既存Runtimeは`InternalStateAwareResponseContextBuilder`を正規`ResponseContextBuilder`として使用している。

そこで次の順に処理する。

```text
Base ResponseContext
→ Emotion / Drive projection
→ ResponseSemanticsPlanner
→ SemanticUtterancePlan.as_context()
→ ResponseContext.memory["semantic_utterance_plan"]
```

境界ではdictへserializeするが、`SemanticUtterancePlan.from_context()`で保守的にtyped contractへ復元可能にする。

この配置によりCharacter Pipeline本体へ直接大きな変更を入れず、#223 Labでも`effective_response_context.memory.semantic_utterance_plan`として観測可能になる。

## #210との移行

#210 / PR #219で導入したtarget-specific evidence Promptは、移行中のCompatibility経路として残す。

正規の将来形:

```text
target-specific structured evidence
→ ResponseSemanticsPlanner
→ SemanticUtterancePlan
→ Character Language Realizer
```

#227でCharacter入力をSemanticUtterancePlan中心へ縮小した時点で、Characterへraw target evidence / Emotion / Driveを直接提示するCompatibility Promptを除去する。

したがって#226では同じPrompt制約を追加し続けない。

## Validatorとの移行

#226では意味Plan生成までを所有する。

#229で以下へ分離する。

```text
structured facts
→ Semantic Validator
→ validated SemanticUtterancePlan
→ Character Language Realizer
→ Realization Validator
```

## 非目標

- Character Profileによる言い回し生成
- Character Promptからraw stateを完全除去すること（#227）
- Semantic/Realization Validator分離（#229）
- Speech Performance（#228）
- Discourse Appraisal再実装（#193）
- fixed Japanese response template
- Emotion名→固定台詞変換

## 検証

最低限、以下を自動テストする。

1. `joy=0 / curiosity高` → `joy=absent`
2. curiosityの値がjoy propositionへ混入しない
3. `current_feeling` → reactive Emotionのsemantic overview
4. `current_desire` → existing semantic Desire concept
5. question / new-direction budget保持
6. Relationship raw数値をPlanへ露出しない
7. serialize / restoreで意味を保持する
8. production `InternalStateAwareResponseContextBuilder`がPlanを添付する

実LLMの自然さ検証は#227以降に#223 Labで行う。
