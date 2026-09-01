# V2 Memory Store / Retrieval D10 binding

Owner: #332
Canonical authority: `memory_store_retrieval_contracts.md`, `memory_operational_numeric_contracts.md`
Related: #321, #327, #364, #359
Status: implementation binding

## 1. 目的

#332 の既存Memory Store / Retrieval実装へ、D10で追加されたretrieval ranking・budget・token estimation・policy freshnessを正本どおり接続する。

本書はMemory semantic Authorityを変更しない。既存のwrite reconciliation、duplicate/provenance merge、supersede、contradiction、Actual Fact境界は維持する。

現行実装に存在する固定score加算値や文字数÷4 token estimateはD10正本ではないためproduction Authorityから除去する。

## 2. Scope

#332で補完する範囲:

- `MemoryRetrievalRankingPolicy`
- `MemoryRankingSignalRule`
- retrieval signal normalization / missing behavior
- canonical weighted score
- deterministic tie-break
- recency half-life
- `MemoryRetrievalQuery` item/token budget enforcement
- canonical token estimator V1
- retrieval result policy / estimator provenance
- current policy revision freshness
- semantic-index unavailable時の明示degradation

#332で扱わない範囲:

- #364 Reflection source/proposal/context bounds
- #359 persistence provider retry/transaction実装
- embedding/vector provider固有score生成
- open-ended duplicate/contradiction判断
- current Internal State / Goal / Relationship Authority

## 3. Ranking policy

production retrievalは明示的に注入されたimmutable/versioned policyを必須とする。

```text
MemoryRetrievalRankingPolicy
- policy_id
- policy_revision
- signal_rules
- recency_half_life_seconds
- stable_tie_breaker
- token_estimator_id
- token_estimator_revision
```

`signal_rules`はclosed `MemoryRankingSignal`をexact指定し、同一signal重複を禁止する。少なくとも1つのpositive weightを必須とする。

```text
MemoryRankingSignalRule
- signal
- weight
- polarity: POSITIVE | NEGATIVE
- missing_behavior: ZERO | EXCLUDE | REJECT_QUERY
```

count/revisionはconcrete `int`、weight/score/secondsはfinite numberとし、bool / NaN / ±Infinityを拒否する。

policy missing時に旧固定weightで継続しない。

## 4. Supported retrieval signals

#332のinitial implementationでは、既存typed record/query/indexからdeterministically供給できるsignalだけをpresentとして扱う。

- `SEMANTIC_RELEVANCE`: semantic-index Portが返すnormalized `[0,1]` score
- `RECENCY`: absolute UTC elapsed ageからhalf-life式で計算
- `CONFIDENCE`: `MemoryConfidence.value`
- `FRESHNESS`: explicit policy score mapを使う場合のみ
- `CONTRADICTION_CONFIDENCE`: typed relation evidenceからnormalized値が供給される場合のみ

`IMPORTANCE`, `RELATIONSHIP_RELEVANCE`, `ACTIVITY_TOPIC_RELEVANCE`, `MOTIVATION_RELEVANCE` 等、現契約からtyped normalized値を取得できないsignalは文字列・kind・query textから推測しない。policyの`missing_behavior`に従う。

## 5. Recency

reference timeはrecordの`observed_at`、無ければ`recorded_at`を使う。

```text
age_seconds = query.created_at_absolute - reference_time_absolute
recency = 2 ** (-age_seconds / recency_half_life_seconds)
```

- absolute instantはUTCへ正規化して比較する
- `age_seconds < 0` はclock skew / invalid recordとしてsilent clampしない
- half-life時は0.5、2 half-life時は0.25

## 6. Missing signal / score formula

各ruleをpolicy順に評価する。

- `ZERO`: value=0としてweightをdenominatorへ含める
- `EXCLUDE`: weightごとdenominatorから除外する
- `REJECT_QUERY`: 1 itemでも必要signalが欠落する場合はqueryをtyped failureへ閉じる

polarity:

```text
POSITIVE: signed_value = value
NEGATIVE: signed_value = 1.0 - value
```

score:

```text
sum(weight * signed_value) / sum(effective_weight)
```

- denominator 0 itemはrankableでないため除外しdiagnosticを残す
- score範囲外をclampしない
- semantic similarity単独でwrite reconciliationへ影響させない

## 7. Deterministic ordering

canonical order:

1. score descending
2. reference observed time descending
3. `memory_id` Unicode code-point lexicographic ascending

repository row order、dict/hash iteration、semantic provider return orderはAuthorityにしない。

## 8. Canonical token estimator V1

```text
estimator_id = memory.utf8_bytes_div3.v1
estimated_tokens(item) = ceil(len(canonical_json_utf8_bytes(item)) / 3)
```

canonical JSON:

- UTF-8
- keys sorted
- compact separators
- NaN禁止
- `ensure_ascii=False`
- envelope/itemのbudget対象payload全体を同じserialization規則で扱う
- empty payloadでも最低1 token unit

plain textを途中sliceしてbudgetへ合わせない。

## 9. Retrieval budget

`MemoryRetrievalQuery.max_items` / `max_estimated_tokens` はともにconcrete `int >= 1`。

ranked itemを順に追加し、次itemでどちらかのbudgetを超える場合、そのitemと以降を返さず `truncated=true` とする。

旧実装の「超過itemだけskipして後続の小さいitemを採用する」挙動は、正本のprefix semanticsへ変更する。

## 10. Semantic index boundary

semantic indexはcanonical Memory stateではない。

D10 rankingでsemantic signalを使う場合、PortはIDだけでなくnormalized `[0,1]` relevanceを返せるtyped境界を持つ。

- range外scoreをclampしない
- provider orderをranking orderとして採用しない
- index unavailable時はtyped degradationを残す
- policyがsemantic signal欠落を`ZERO`/`EXCLUDE`として許す場合のみsafe degraded retrievalを継続する
- `REJECT_QUERY`ならfail-closed

既存write-side index upsert failure semanticsは維持する。

## 11. Policy freshness / provenance

`MemoryStoreAuthority`はcurrent `MemoryRetrievalRankingPolicy` generationを所有または明示Portから参照する。

`MemoryEvidenceView`は最低限以下をprovenanceとして保持する。

- ranking policy id / revision
- token estimator id / revision

retrieval開始時のpolicy generationと結果commit時のcurrent generationが異なる場合、old resultをnew policyへ付け替えない。

現行#332 retrievalは同期処理だが、将来semantic-index Portがasync化されても同じgeneration fenceを適用できる契約にする。

## 12. Compatibility

次は変更しない。

- exact canonical duplicate suppression
- provenance merge
- typed supersede / contradiction relation
- semantic similarityをwrite Authorityへしない原則
- repository unavailable / index update failureのtruthful degradation
- Actual Speech / Activity Fact境界
- current state/Goal/Relationship非所有

## 13. Required tests

- strict numeric: bool / NaN / ±Infinity reject
- duplicate signal / zero-positive-weight policy reject
- recency half-life 0.5 / two half-life 0.25
- future reference timestamp fail-closed
- POSITIVE / NEGATIVE formula
- ZERO / EXCLUDE / REJECT_QUERY
- denominator 0 item除外
- deterministic tie-break score → time → id
- UTF-8 estimator ASCII / 日本語 / structured payload
- item budget `< / == / >`
- token budget `< / == / >`
- budget超過時prefix終了、途中text sliceなし
- semantic index unavailable safe degradation / required signal fail-closed
- policy provenanceをresultへ保持
- policy revision変更時にold generationをcurrentとして扱わない
- semantic similarity単独でduplicate/merge/supersedeしない既存回帰
