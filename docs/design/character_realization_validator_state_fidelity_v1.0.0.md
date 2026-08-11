# Character Realization Validator State Fidelity v1.0.0

## 位置付け

Parent #225 / Work #229 / Draft PR #233。

Extended Verificationで、Character Language RealizerがSemantic Planのstateを弱化・polarity化・supporting propositionで部分保持した発話を生成し、Character Realization Validatorがfalse acceptするケースが確認された。

本設計は#227 State Fidelity Unit + #226→#227 Adjacentを再freezeした後の、第二防衛線として#229だけを修正する。

文体品質・Characterらしさは採点しない。確定済みSemantic PlanとCharacter speechの意味保持だけを対象とする。

## 観測したfalse accept類型

### E1: explicit intensityのpresence化

Plan:

```text
joy = high / certainty=high
```

Character:

```text
うん、楽しいよ。
```

joyの存在は保持しているが、highとmere presentを区別する強度意味が失われている。`state_preserved=true`ではなくweakenedとして扱う。

### E2/E3: unknownのpolarity確定

Plan:

```text
sadness = unknown
```

Character例:

```text
ううん、悲しいとは言えないかな。
うん、悲しいよ。
```

yes/no質問に対する肯定・否定markerを含め、speech全体がpresent/absentを確定する場合はunknown保持違反。

### E4: supporting propositionのpartial realization

Plan:

```text
current_feeling = overview
joy = high
anger = moderate
calm = low
amusement = absent
```

Characterがsupporting propositionのrealization IDを列挙してspeechへ採用した場合、primaryだけでなく採用した各supporting propositionのstate/certainty/conceptも検証する。

supporting proposition自体は省略可能。省略したものをreject理由にしない。

## 原則

1. Semantic Planが正本。raw Emotion/Drive/evidence値を再参照しない。
2. state fidelityは自然言語意味としてValidator LLMに判定させる。
3. 特定の日本語程度語→state辞書を作らない。
4. Runtime deterministic guardは、語がどのpropositionへ掛かるかを推測しない。
5. accepted=trueはLLMの1個の集約boolだけでは成立させず、Characterが採用したpropositionごとの構造診断をRuntimeでfail closed確認する。

## Character-facing Semantic View

各propositionに次を追加する。

- `realization_policy`
  - primary: `required`
  - supporting: `optional_but_facet_complete_if_realized`
- `if_realized_required_facets`
  - predicate
  - state
  - certainty
  - concept（non-null時のみ）
- `state_semantics`
  - present: `presence_without_intensity`
  - absent: `absence`
  - unknown: `unknown_without_polarity_guess`
  - low/moderate/high/very_high: `explicit_intensity_state`
- `state_fidelity`: `preserve_exact_semantic_state`
- `intensity_fidelity`
  - intensity state: `must_preserve_intensity_if_realized`
  - その他: `not_applicable`
- `polarity_commitment`
  - unknown: `forbidden`
  - その他: `bounded_by_state`

## Validator Output Schema

既存top-level:

- `accepted`
- `reason`
- `differences`
- `semantic_checks`
- `surface_evidence`

を維持し、accepted=true時に次を必須化する。

```json
{
  "realized_proposition_checks": [
    {
      "realization_id": "proposition:0:joy",
      "predicate_preserved": true,
      "state_preserved": true,
      "state_fidelity": "exact",
      "certainty_preserved": true,
      "concept_preserved": true
    }
  ]
}
```

### state_fidelity enum

- `exact`: Planのstate意味を保っている
- `weakened`: high→mere present等、Planより弱い
- `strengthened`: low/moderate→より強い等、Planより強い
- `polarity_changed`: present↔absent等の反転
- `unknown_committed`: unknownをpresent/absent/強度stateへ確定
- `omitted`: realizationを主張しているがspeechでstateが識別できない

### 判定ルール

Characterの`semantic_realizations`へ列挙された、Plan内の各realization IDについてcheckを**ちょうど1件**要求する。

accepted=true時:

- primary IDのcheck必須
- supporting IDをCharacterが列挙した場合、そのcheckも必須
- Characterが列挙していないsupporting propositionのcheckは要求しない
- unknown/unplanned realization IDはfail closed
- duplicate checkはfail closed
- `predicate_preserved/state_preserved/certainty_preserved/concept_preserved`はbool必須
- `state_fidelity`は上記enum必須
- `state_preserved=true`かつ`state_fidelity != exact`の矛盾はreject
- `state_fidelity=exact`以外はreject
- concept=nullでも`concept_preserved` boolを要求し、trueをnot-applicable-preservedとして扱う

既存primary aggregate `semantic_checks`は維持し、後方診断・regeneration feedbackに使う。個別checkと矛盾した場合はacceptしない。

## Validator Prompt判定基準

### explicit intensity

`low/moderate/high/very_high`はmere presentではない。

speechが「そのstateがある」ことだけを伝え、Planの強度差を意味的に識別できない場合は `state_fidelity=weakened`。

固定の程度副詞を要求しない。語彙、構文、強調等どの自然な手段でもよい。

### unknown

`state=unknown`はpresent/absentではない。

yes/no型User Wording Hintに対する「うん」「ううん」「そう」「違う」等も、speech全体としてpolarityを確定するなら `unknown_committed`。

「判断できない」「はっきりしない」等でpolarityを確定しない場合だけexactになり得る。

### supporting proposition

supporting propositionは省略可能。

ただしCharacterの`semantic_realizations`にIDがある場合、そのpropositionをspeechへ採用した主張なので、predicate/state/certainty/conceptを独立に評価する。

primaryが正しくても、採用済みsupporting propositionがweakened/strengthened/unknown_committed等なら全体reject。

## Runtime Fail-Closed

accepted=trueを受け取った場合、Runtimeは:

1. Schema型を検証
2. Planからknown realization ID集合を構築
3. Character `semantic_realizations`のIDがknownか確認
4. 各Character realization IDにexactly one `realized_proposition_checks`があることを確認
5. 各checkのboolとstate_fidelityを確認
6. 1件でもnon-exact/falseなら`semantic_facet_validation_failed`
7. missing/duplicate/unknown/type invalidは`realization_validator_schema_invalid`または明示差分でfail closed

LLMがtop-level `accepted=true`でも、この構造条件を満たさなければ採用しない。

## Deterministic Surface Guard

既存のPlan-wide intensity marker guardは維持する。

Plan内にintensity stateが存在する場合、どの程度語がどのpropositionへ掛かるかをdeterministicに推測しない。E4のような帰属判定はValidator LLMのper-proposition checkへ委譲する。

## Unit Gate

最低限:

1. Promptがexplicit intensityのpresence化をweakenedと定義
2. Promptがunknown yes/no polarity確定をunknown_committedと定義
3. Promptがsupporting realized propositionを個別評価する契約を持つ
4. accepted=trueで`realized_proposition_checks`欠落 → schema invalid
5. primary highが`state_fidelity=weakened` → Runtime reject
6. primary unknownが`state_fidelity=unknown_committed` → Runtime reject
7. primary aggregateがtrueでもsupporting checkがweakened → Runtime reject
8. Character realization IDに対応するcheck欠落/duplicate/unknown → fail closed
9. valid primary/supporting checkが全てexact → accept
10. raw Emotion/Drive/evidence pathはPrompt/Model contextへ流さない
11. 既存Plan-wide deterministic marker guardを後退させない

## 非目標

- Character LLM #227の追加修正
- fixed phrase/intensity dictionary
- Speech Performance / TTS / Body
- Characterらしさ・自然さの品質採点
- full runtime integration

## 次工程

1. 本設計を#229へ固定
2. freeze済み#227 HEADを#229へ同期
3. #229実装 + Unit gate
4. PASS後に#226→#227→#229 Adjacent
5. PASS後にSemantic Labへ同期しfocused CI
6. Extended Verification 6ケースを同一current HEADで実LLM再実行
