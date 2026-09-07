# V2 Memory Operational / Numerical Contracts

Owners: #332 / #364
Related: `memory_store_retrieval_contracts.md`, `memory_reflection_contracts.md`, `runtime_operational_numeric_contracts.md`
Design gate: #445 D10
Status: Canonical Supplement / implementation-decidability correction

## 1. 目的

Memory retrievalのranking/budgetとReflection context/batch boundsを、実装者のhidden weights、token estimator、source count、proposal countへ委ねずdeterministic/versioned policyとして固定する。

本書はMemory semantic Authorityを変更しない。semantic similarityはranking signalであり、duplicate/merge/supersede Authorityにはならない。

## 2. Common strict numeric rule

本書のcount/revisionはconcrete `int`、ratio/score/secondsはfinite numberを要求し、Python `bool`をnumberとして受理しない。NaN/±Infinityを拒否する。

## 3. Retrieval ranking policy

```text
MemoryRetrievalRankingPolicy
- policy_id: non-empty stable identity
- policy_revision: non-negative int
- signal_rules: unique tuple[MemoryRankingSignalRule]
- recency_half_life_seconds: finite float > 0
- stable_tie_breaker: SCORE_DESC_OBSERVED_AT_DESC_MEMORY_ID_ASC
- token_estimator_id
- token_estimator_revision: non-negative int

MemoryRankingSignalRule
- signal:
    SEMANTIC_RELEVANCE
    RECENCY
    IMPORTANCE
    CONFIDENCE
    RELATIONSHIP_RELEVANCE
    ACTIVITY_TOPIC_RELEVANCE
    MOTIVATION_RELEVANCE
    FRESHNESS
    CONTRADICTION_CONFIDENCE
- weight: finite float >= 0
- polarity: POSITIVE | NEGATIVE
- missing_behavior: ZERO | EXCLUDE | REJECT_QUERY
```

Rules:

- signalはpolicy内で重複不可。
- 少なくとも1つの`weight > 0`を必須とする。
- raw natural-language field名やMemory kind名からweightを生成しない。
- policy missing/invalid時、hidden default rankingで続行しない。exact/filter-only retrievalへ明示degradeできる場合だけ`degraded=true`で継続し、otherwise fail-closed。
- queryごとにweightをLLMへ決めさせない。purpose別policyが必要なら別`policy_id/revision`を明示する。

## 4. Signal normalization

全ranking signalは最終的に`[0,1]`へ正規化済みのtyped valueとしてRanking Authorityへ渡す。

### 4.1 Recency

対象recordの`observed_at`がある場合それを、なければ`recorded_at`をreference timeとする。

```text
age_seconds = max(0, query.created_at_absolute - reference_time_absolute)
recency = 2 ** (-age_seconds / recency_half_life_seconds)
```

future reference timeはclock skewとしてsilent clampせずtyped invalid-record diagnosticへ閉じる。queryより後のMemoryを「最も新しい」として1へclampしない。

### 4.2 Confidence / importance / semantic relevance

source contractが`[0,1]`を保証する値だけ受理する。範囲外をsilent clampしない。

### 4.3 Freshness

Memory lifecycle/temporal freshness enumからscoreへ投影する場合はpolicy dataへexact mappingを持つ。

```text
MemoryFreshnessScoreMap
- freshness_state -> score in [0,1]
```

supportする全freshness stateをexactly once覆う。未知stateを文字列から推測しない。

### 4.4 Contradiction

`CONTRADICTION_CONFIDENCE`はcontradiction relation/evidenceからownerが供給する`[0,1]` signalであり、relationの存在だけをbool-as-numberで扱わない。通常は`polarity=NEGATIVE`で設定するが、policyに明示する。

## 5. Ranking formula

各itemについて、policy signalを順に評価する。

`missing_behavior`:

- `ZERO`: value=0としてweightをdenominatorへ含める。
- `EXCLUDE`: そのsignalのweightをそのitemのdenominatorから除外する。
- `REJECT_QUERY`: 必要signalを確定できない時点でquery全体をtyped failureにする。

各present/effective signalのsigned contribution:

```text
signed_value = value                  if POSITIVE
signed_value = 1.0 - value            if NEGATIVE
```

score:

```text
score = sum(weight_i * signed_value_i) / sum(effective_weight_i)
```

- denominatorが0ならそのitemはrankableでなく除外しdiagnosticを残す。全itemが除外ならempty/degraded result。
- result scoreは計算上`[0,1]`でなければならず、範囲外をclampしない。
- tie-breakは`score desc` → `reference observed time desc` → `memory_id Unicode code-point lexicographic asc`。
- DB row order、hash iteration order、embedding provider return orderをtie-break Authorityにしない。

## 6. Retrieval budgets

`MemoryRetrievalQuery`:

- `max_items`: int >= 1
- `max_estimated_tokens`: int >= 1

候補をranking順に走査し、次item追加によりどちらかのbudgetを超える場合、そのitemと以降を返さず`truncated=true`とする。budgetを超えてから末尾を切るためにplain-textを途中sliceしない。

### 6.1 Canonical token estimator V1

Provider tokenizerへCoreを依存させないため、initial canonical estimatorを次とする。

```text
estimator_id = memory.utf8_bytes_div3.v1
estimated_tokens(item) = ceil(len(canonical_json_utf8_bytes(item)) / 3)
```

- canonical JSONはUTF-8、keys sorted、compact separators、NaN禁止、UnicodeはUTF-8実体として数える。
- envelope fixed overheadも同じserialization対象に含める。
- empty itemでも最低1 token unit。
- estimatorは「実Provider tokenizerの正確なtoken数」ではなくbounded retrieval用deterministic estimate。
- estimator変更は`token_estimator_revision`を進める。hidden tokenizer切替をしない。

## 7. Reflection operational policy

```text
ReflectionOperationalPolicy
- policy_id
- policy_revision: non-negative int
- max_primary_sources: int >= 1
- max_related_memory_items: int >= 0
- max_context_estimated_tokens: int >= 1
- max_source_excerpt_codepoints: int >= 0
- max_proposals_per_reflection: int >= 1
- max_relation_hints_per_proposal: int >= 0
- max_evidence_refs_per_proposal: int >= 1
- max_concurrent_reflections: int >= 1
```

- `max_concurrent_reflections`は#322 lane policyと矛盾してはならず、effective concurrencyは両方の小さい方。
- source excerpt lengthはUnicode code point数で測る。byte sliceでUTF-8を破壊しない。
- source excerptを切る場合、truncated metadataを保持し、切断片から「全文を読んだ」と主張しない。
- context estimated tokenはSection 6 estimatorを使用する。別estimatorを使うならpolicy identity/revisionへbindする。
- proposal数超過Provider responseはfirst-Nとしてsilent acceptせずschema/policy violationとしてrejectする。Provider orderをimportance Authorityにしない。
- relation/evidence refs上限超過もsilent truncateせずinvalid proposal。

## 8. Reflection source selection

Reflection contextへsourceを入れる順はraw arrival orderだけに依存しない。triggerが明示する`source_refs`をprimary setとし、次をstable orderingとする。

```text
occurred_at asc
→ source_kind canonical enum order
→ source_ref Unicode code-point lexicographic asc
```

`max_primary_sources`超過のtriggerは入力作成時にfail-closedするか、trigger ownerが事前に明示batch/coalesceして新しいbounded trigger generationを作る。Reflection内部で先頭N件を勝手に捨てない。

related memoryは#332 ranking結果をそのままbounded viewとして使い、Reflectionが独自のhidden rerankingを行わない。

## 9. Policy freshness

Retrieval resultはranking policy identity/revisionとtoken estimator identity/revisionをprovenanceとして保持する。

Reflection requestはoperational policy identity/revisionをcontext generationへbindする。

async Provider await中にpolicy revisionが変わった場合:

- old context/proposal/support resultをnew policy revisionへ付け替えない。
- current policyと互換性がowner contractで明示されていない限りold generationをstale/supersededとして閉じる。
- retryはnew request generationとして行う。

## 10. Persistence/backpressure relation

#332/#364が生成するrepository/index/persistence workのretry/backoff/cancellation graceは`runtime_operational_numeric_contracts.md`と#350 failure classificationを使用する。

Memory/Reflectionが独自の無期限retry loopやunbounded queueを持たない。

## 11. Required tests

- recency half-lifeで0.5、2 half-lifeで0.25
- positive/negative polarityのclosed formula
- missing ZERO/EXCLUDE/REJECT_QUERY
- denominator 0 item除外
- deterministic tie-break
- future timestampをsilent clampしない
- UTF-8 estimator ASCII/日本語/structured payload deterministic
- item/token budget境界、途中text sliceなし
- Reflection count/token/excerpt bounds
- proposal/ref上限超過をsilent truncateしない
- policy revision中のlate result stale
- semantic similarity単独でduplicate/mergeしない
