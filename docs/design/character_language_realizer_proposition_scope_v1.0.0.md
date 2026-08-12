# Character Language Realizer Proposition Scope v1.0.0

## 位置づけ

Parent #225 / Work #227 / Draft PR #232。

2026-08-12の#223 Live Verification（Basic4 + E1-E8）で、12 requestは全件成功したが、意味保持は7 validated / 5 fallbackだった。本書は、そのうちCharacter Language Realizer責務に属する4件を、個別の日本語言い換えではなくproposition-level contractとして修正する。

## Liveで確認した原因

### 1. certaintyのscope分裂

`current_desire=present / certainty=medium / concept=curiosity`で、predicateを無標断定し、conceptだけをhedgeする候補が生成された。

これはproposition全体ではmedium certaintyではなく、一部のfacetだけがmediumになっている。

### 2. unknown stateとcertaintyの混同

`state=unknown / certainty=low`では、unknownというstateを明確に断定するだけでは`certainty=high`相当になり得る。

certaintyは「predicateのstateはunknownである」という命題へのepistemic commitmentとして、unknown判定そのものへ作用させる。

### 3. optional supporting propositionのpartial realization

`current_feeling`のsupporting `calm=moderate`を、Characterが単なる`present`相当へ弱めたままsemantic_realizationsへ列挙した。

supportingはoptionalなので、facet-completeに実現できない場合は部分的な意味を残さず、speechとsemantic_realizations IDを一緒に省略する。

## 正規契約

### certainty scope

各propositionに次を付与する。

```text
certainty_scope = entire_proposition
```

primaryのRequired Facet Realization Contractでは、non-null conceptがある場合:

```text
certainty_scope_components = predicate / state / concept
```

conceptがnullなら:

```text
certainty_scope_components = predicate / state
```

medium/low certaintyのpropositionを複数節へ分けても、一部の節だけをPlanより強く断定しない。

### unknown certainty

`state=unknown`では:

```text
unknown_certainty_semantics = epistemic_commitment_to_unknown_state_judgment
```

とし、unknownを特定polarityへcommitしないことと、unknown判定そのものへのcertaintyを別facetとして保持する。

### optional supporting all-or-omit

supporting propositionは:

```text
realization_policy = optional_but_facet_complete_if_realized
optional_failure_policy = omit_entire_proposition_if_facet_incomplete
```

全体policy:

```text
supporting_failure_policy = omit_entire_optional_proposition_if_facet_incomplete
```

regenerationでもoptional supportingをfacet-completeに修復できなければ、表現とIDを両方省略する。primary propositionは省略しない。

## Regeneration feedback

certainty mismatchでは:

- `restore_certainty_as_epistemic_modality`
- `restore_proposition_level_certainty_scope`

を返す。

state/certainty/predicate/conceptのsupporting mismatchでは:

- `drop_optional_realization_if_facet_incomplete`

を追加し、optionalならpartial realizationを残さない。

## 禁止事項

- low / moderate / high等を特定の日本語単語・副詞へ固定対応しない。
- unknown / certaintyを有限語彙・regex・substringで判定しない。
- Liveで失敗した具体文を禁止語・正解文として登録しない。
- Character Profileを意味変更の根拠にしない。

## Gate

Unit/Adjacentでは最低限:

1. medium certaintyが`entire_proposition` scopeを持つ。
2. non-null conceptを含むpropositionでcertaintyがpredicate/state/concept全体へ作用する。
3. `unknown + low`がunknown判定への低certaintyとして契約化される。
4. optional supportingがfacet不完全ならall-or-omitできる。
5. regeneration feedbackが上記の構造修復constraintへ接続される。
6. finite natural-language semantic matcherを追加していない。

Liveでは前回fallbackになった `current_feeling_repeat`、`current_desire`、`extended_sadness_unknown_low`、`extended_current_desire_connection`を再確認する。
