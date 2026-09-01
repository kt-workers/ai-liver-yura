# V2 Memory Reflection D10 operational binding

Owner: #364
Canonical authority: `memory_reflection_contracts.md`, `memory_operational_numeric_contracts.md`
Related: #322, #323, #332, #359
Status: implementation binding

## 1. 目的

既存#364 Reflection coreのproposal/support/closed acceptanceを維持しつつ、D10で追加されたcontext/batch/concurrency/freshness数値契約を明示的なversioned policyへ接続する。

旧実装に存在する`primary_sources=32`、`related_memory_view=64`、`max_estimated_tokens=4096`、`max_concurrency=2`等のowner数値をproduction Authorityとして残さない。

## 2. Scope

#364で補完するもの:

- `ReflectionOperationalPolicy`
- primary/related/context token/source excerpt bounds
- proposal/relation/evidence bounds
- Reflection local concurrency bound
- #322 lane concurrencyとのeffective min
- canonical source ordering
- source excerptのcodepoint単位truncation metadata
- provider response overflowのfail-closed
- operational policy generation provenance/freshness
- canonical Memory token estimator V1によるcontext estimate

扱わないもの:

- #332 Store/Retrieval ranking semantics
- #359 persistence retry/transaction
- #323 provider retry/deadline
- Reflection acceptance意味論の変更
- raw NLからMemory relation/importanceを新たに推測すること

## 3. ReflectionOperationalPolicy

```text
ReflectionOperationalPolicy
- policy_id
- policy_revision
- max_primary_sources: int >= 1
- max_related_memory_items: int >= 0
- max_context_estimated_tokens: int >= 1
- max_source_excerpt_codepoints: int >= 0
- max_proposals_per_reflection: int >= 1
- max_relation_hints_per_proposal: int >= 0
- max_evidence_refs_per_proposal: int >= 1
- max_concurrent_reflections: int >= 1
```

すべてconcrete `int`を要求し、boolを拒否する。production hidden defaultは持たない。

## 4. Context generation binding

`ReflectionContextSnapshot`は`operational_policy_id/revision`を必須provenanceとして保持する。

contextはprovider invocation前にcurrent policyとexact一致を検証する。

- `primary_sources` > `max_primary_sources`: fail-closed。first-N禁止。
- `related_memory_view` > `max_related_memory_items`: fail-closed。Reflection内部で#332結果を再rankingしない。
- context canonical estimated tokens > `max_context_estimated_tokens`: fail-closed。
- trigger source refsとprimary sourcesはexact一致を維持する。

DTOはD10 owner数値の別Authorityを持たない。JSON depth/型等の構造安全制約は別契約として維持できる。

## 5. Source ordering / excerpt

primary source canonical order:

```text
occurred_at asc
→ ReflectionSourceKind declaration/canonical order asc
→ source_ref Unicode code-point lexicographic asc
```

Reflectionはover-limit source集合を勝手に切らない。trigger ownerが事前batch/coalesceした新generationを作る。

raw text excerptが必要な場合は`source_excerpt`と`source_excerpt_truncated`を明示する。

- lengthはUnicode code point数。
- `max_source_excerpt_codepoints=0`ならnon-empty excerpt不可。
- truncateは先頭codepoint境界でのみ行い、metadataを`true`にする。
- byte sliceやtruncated metadata無しの黙示切断は禁止。

## 6. Canonical context token estimate

Reflection context budgetは#332と同じcanonical estimatorを使用する。

```text
memory.utf8_bytes_div3.v1
ceil(len(canonical_json_utf8_bytes(payload)) / 3)
```

UTF-8 / sorted keys / compact separators / NaN禁止 / `ensure_ascii=False`。

`estimated_tokens`はcontext内容からdeterministically算出し、caller supplied guessをAuthorityにしない。

## 7. Proposal / support bounds

proposal provider result:

- proposal count > `max_proposals_per_reflection`: response全体をpolicy violationとしてreject。first-N禁止。
- relation hint count > `max_relation_hints_per_proposal`: proposal invalid。
- proposalに含まれるrationale/relation evidence refsのbounded set > `max_evidence_refs_per_proposal`: proposal invalid。

support observer result:

- evidence / unsupported / contradiction refsを合わせたbounded evidence set > `max_evidence_refs_per_proposal`: proposal invalid。
- overflow refを切り落としてacceptしない。

既存source grounding、actual speech/activity fact、relation revision、support relation validationはそのまま後段で適用する。

## 8. Concurrency

`max_concurrent_reflections`は#364 local上限。

#322 laneが別上限を供給する場合:

```text
effective = min(reflection policy max_concurrent_reflections, lane max concurrency)
```

pending task capacityは#322/backpressure側から明示注入し、#364内にhidden queue sizeを生成しない。

foregroundはReflection completionをawaitしない。既存coalescing/cancel/deferred semanticsを維持する。

## 9. Policy freshness

proposal await / support awaitの各境界後にcurrent operational policy generationを再確認する。

- generation変更後のold proposalをnew policyへ付け替えない。
- proposal await中にstale: support開始せず`REJECTED_STALE`へ閉じる。
- support await中にstale: acceptanceへ進めず`REJECTED_STALE`へ閉じる。
- unrelated current-state driftだけでhistorical sourceをstaleにする既存挙動は導入しない。

## 10. Compatibility

維持する:

- proposalとsupport observerの論理分離
- support provider unavailableのfail-closed
- trusted deterministic captureのclosed path
- actual speech/activity truth boundary
- relation revision live revalidation
- same immutable context coalescing
- corrected/retracted source hard stale
- #332 Storeを直接mutationしない境界
- aggregate telemetry

## 11. Required tests

- policy strict numeric / bool reject
- context primary source `< / == / >`
- related memory `< / == / >`
- context token budget boundary
- source canonical ordering
- Unicode source excerpt boundary / truncation metadata
- proposal count exact/overflow no first-N
- relation hints exact/overflow
- evidence refs exact/overflow
- support refs exact/overflow
- effective concurrency = min(#364, #322)
- policy revision changes during proposal await
- policy revision changes during support await
- zero candidate / coalescing / cancel / provider unavailable existing regression
