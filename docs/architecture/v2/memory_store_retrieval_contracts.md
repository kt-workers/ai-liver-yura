# V2 Memory Store / Retrieval Contracts

Owner Issue: #332
Parent: #325
Related: #321, #326, #327, #328, #333, #364, #366
Status: Canonical Supplement / Design Gate

## 1. Purpose

本書は、AI Liver ゆら V2におけるMemoryの**正本Store・統合・矛盾管理・Retrieval**を定義する。

Memoryは「過去の会話をそのまま保存する箱」ではない。

```text
validated MemoryCandidate / trusted typed source
        ↓
Memory validation / routing / reconciliation
        ├─ reject
        ├─ store new
        ├─ merge provenance
        ├─ supersede / refine
        └─ link contradiction
        ↓
Canonical Memory Records
        ↓
Retrieval Query + bounded ranking
        ↓
MemoryEvidenceView
        ↓
Input Meaning / Appraisal / Executive / Reflection context
```

#332はMemory内容をopen-endedに発明するLLM Roleではない。

- #364 Reflection: 何を覚える価値があるかをMemoryCandidateとして提案できる
- #332 Memory Store: candidateを検証し、正本Memoryへどう反映するかを決める
- DB / vector index / embedding provider: #332 Portの外側

Memory canonical store/retrievalは非LLM Authorityとする。

---

## 2. Authority boundary

### #332 owns

- canonical Memory record identity / revision / lifecycle
- Memory kind / retention class
- provenance / source references
- freshness / temporal scope / confidence metadata
- duplicate-safe storage
- refinement / supersession lifecycle
- contradiction links
- bounded retrieval policy
- `MemoryEvidenceView`
- persistence/index degradation state

### #332 does not own

- raw natural-language meaning interpretation
- current Emotion / Desire / Drive / Motivation
- current Relationship state
- current Goal / Commitment
- current Execution Fact
- Character personality definition
- open-ended判断「これは人生で重要だから覚えるべき」
- final Goal / Action choice

### Adjacent authorities

- #326 Input Meaning owns open-ended external NL semantics.
- #327 owns current Appraisal / Internal State / Relationship current state.
- #328 owns conscious Goal / Action selection.
- #366 owns current Goal / Commitment canonical state.
- #329 owns Activity lifecycle / Actual Execution Fact.
- #364 may generate MemoryCandidate, but cannot write the canonical Memory Store directly.

Memory is historical/contextual evidence. It must never silently become a stronger current-fact authority than the module that owns the current state or fact.

---

## 3. Memory categories

Initial V2 categories are closed structural routing categories, not natural-language semantic labels.

```text
WORKING
EPISODIC
SEMANTIC
RELATIONSHIP
PREFERENCE
ACTIVITY_SKILL
```

### WORKING

Short-lived context retained for bounded continuity. It is not automatically durable long-term memory.

Examples of eligible content class:
- recent resolved reference context
- recent interaction state needed across a small number of turns
- temporary task context

### EPISODIC

A time-bounded event/experience record with explicit provenance.

### SEMANTIC

A relatively stable learned fact/belief candidate about the world or a subject, with confidence and temporal scope.

### RELATIONSHIP

Historical evidence relevant to interaction with a specific counterparty. This is not the current Relationship state itself.

### PREFERENCE

Historical/static preference evidence. This is distinct from current Interest/Curiosity.

### ACTIVITY_SKILL

Past activity/result/learning evidence. It is not an Activity lifecycle or Actual Execution Fact authority.

New categories require a schema/design change. Arbitrary natural-language tags must not silently become new authority categories.

---

## 4. Canonical data contracts

### 4.1 MemoryId / revision

Every canonical record has stable identity and monotonic revision.

```text
memory_id
revision
```

A stale expected revision must not overwrite a newer canonical record.

### 4.2 MemoryContent

Memory content is typed structured content, not an unbounded opaque prompt transcript.

Minimum shape:

```text
MemoryContent
- subject_ref?
- predicate / content_kind
- value
- temporal_scope?
- qualifiers[]
```

`value` may contain bounded JSON-compatible structured data, but the Store does not reinterpret arbitrary raw text as a new semantic fact.

Conversation text may be retained as source evidence when explicitly permitted, but raw conversation history is not the canonical semantic identity of every Memory record.

### 4.3 MemoryProvenance

Every non-working durable record must trace back to evidence.

```text
MemoryProvenance
- source_event_refs[]
- source_fact_refs[]
- source_memory_candidate_id?
- source_kind
- observed_at?
- recorded_at
```

Source references are immutable historical evidence references. A later source must not rewrite an earlier source out of history.

### 4.4 Temporal / confidence state

```text
MemoryTemporalState
- valid_from?
- valid_until?
- observed_at?
- freshness_state

MemoryConfidence
- confidence
- basis
```

Freshness and confidence affect retrieval/evidence use but do not alone convert a Memory into a current fact.

A low-confidence record may remain useful historical evidence if clearly labelled. A stale record is not necessarily deleted.

### 4.5 Memory lifecycle

Initial lifecycle:

```text
ACTIVE
SUPERSEDED
ARCHIVED
```

Contradiction is a relation between records, not a destructive lifecycle state by itself.

Deletion/physical purge is a persistence/data-retention concern and is not the ordinary semantic update mechanism.

---

## 5. MemoryCandidate input

#332 accepts only a typed `ValidatedMemoryCandidate` boundary.

Minimum shape:

```text
ValidatedMemoryCandidate
- candidate_id
- memory_kind
- content
- provenance
- confidence
- importance_hint?
- temporal_scope?
- suggested_related_memory_ids[]
- suggested_relation_hints[]
- source_context_revision?
- created_at
```

`importance_hint` and relation hints are **candidate evidence**, not final Store authority.

Candidate may originate from:
- #364 Reflection
- trusted typed user-provided fact path
- Activity/Execution Result projection
- explicit deterministic system event

A module must not bypass this boundary and directly mutate a MemoryRecord.

---

## 6. Write reconciliation

Canonical dispositions:

```text
STORE_NEW
NOOP_DUPLICATE
MERGE_PROVENANCE
SUPERSEDE
LINK_CONTRADICTION
REJECT
```

### STORE_NEW

Use when no canonical record is being replaced/merged and provenance is sufficient.

### NOOP_DUPLICATE

Exact canonical duplicate with no meaningful new provenance. Repeated identical input must not create unbounded duplicate rows.

### MERGE_PROVENANCE

Content identity is already canonical, but the new candidate adds independent supporting provenance. Preserve both old and new source references.

### SUPERSEDE

A newer/stronger record explicitly replaces the current applicability of an older record while preserving history.

Supersede is preferred over destructive overwrite.

Example:

```text
old: user prefers game A, valid_from T1
new: user says they no longer like game A, valid_from T2

→ preserve old historical record
→ create/update new record
→ old record becomes SUPERSEDED for current preference use
```

The Store must not infer this natural-language contradiction itself from surface words. It consumes typed candidate/relation evidence and applies deterministic lifecycle rules.

### LINK_CONTRADICTION

When two records conflict but the system lacks authority/evidence to choose a winner:

- preserve both
- add bidirectional contradiction relation
- expose contradiction in retrieval evidence
- do not silently average or choose the most recent solely because it is recent

### REJECT

Reject at minimum:
- missing/invalid provenance where provenance is required
- malformed typed content
- impossible kind/lifecycle transition
- stale expected revision write
- candidate claiming current-state authority outside Memory
- unsupported relation target
- attempt to treat prepared-but-not-presented speech as actual spoken history

---

## 7. Duplicate / semantic similarity boundary

Embedding/vector similarity is a retrieval/search signal, not Memory identity Authority.

Forbidden:

```text
cosine_similarity > threshold
→ therefore duplicate
→ overwrite/merge automatically
```

Allowed:

```text
index similarity
→ candidate related records
→ typed reconciliation evidence
→ deterministic Store policy
```

Exact stable identity/content digest may be used for deterministic exact duplicate suppression.

Open-ended claims such as synonymy, contradiction, refinement, or temporal replacement require typed upstream observation/evidence; #332 itself does not become a hidden natural-language LLM.

---

## 8. Contradiction model

A canonical record may reference zero or more conflicting records.

```text
MemoryRelation
- relation_id
- left_memory_id
- right_memory_id
- relation_kind
- evidence_refs[]
- created_at
```

Initial relation kinds:

```text
SUPPORTS
REFINES
SUPERSEDES
CONTRADICTS
```

Relation kinds are closed structural relations. Discovery of an open-ended semantic relation may be proposed by #364 or another typed observer, but #332 validates references and owns persistence of the accepted relation.

`CONTRADICTS` does not imply either side is current truth.

Consumers receive enough metadata to avoid treating a conflicted Memory as uncontested evidence.

---

## 9. Actual fact / speech boundary

Memory must preserve the distinction between:

```text
intent
plan
prepared candidate
presented/observed action
actual execution result
historical memory
```

In particular:

- `PreparedSpeechCandidate` is not proof that Yura actually said something.
- `CharacterUtterance` generation is not proof of presentation.
- a speech episode Memory that claims “Yura said X” requires presentation/actual speech evidence from the owning runtime boundary.
- an Activity Memory that claims execution requires #329 Actual Execution Fact evidence.

Memory may record that a plan/candidate existed if the Memory content explicitly says it was a plan/candidate. It must not relabel it as an executed fact.

---

## 10. Relationship / preference / internal-state boundary

### Relationship

`RELATIONSHIP` Memory stores historical evidence such as prior interactions or relationship-relevant events.

It does not directly set #327 current Relationship state.

```text
Relationship Memory evidence
→ Appraisal / State Reducer input
→ current Relationship state transition
```

### Preference

`PREFERENCE` Memory can store evidence that a preference existed/was stated. Current active preference may be derived/evaluated by the consuming authority with freshness/conflict information.

### Internal State

Past Emotion/Desire/Drive may be stored as an episode only when historically useful, but retrieving it must never directly restore that value into current Internal State.

```text
past emotion Memory
≠ current emotion
```

---

## 11. Retrieval contract

### 11.1 MemoryRetrievalQuery

A retrieval query is bounded and typed.

```text
MemoryRetrievalQuery
- query_id
- requester
- purpose
- memory_kinds[]?
- subject_refs[]?
- topic/activity/relationship refs[]?
- temporal_range?
- semantic_query?
- max_items
- max_estimated_tokens
- include_conflicted
- created_at
```

`semantic_query` is optional search input for a semantic-index Port. #332 does not interpret arbitrary natural language itself.

### 11.2 Retrieval signals

Ranking may combine:

- semantic relevance signal
- recency
- importance
- confidence
- relationship relevance
- activity/topic relevance
- current motivation relevance supplied as a typed signal
- freshness
- contradiction status

Weights/policy are explicit deterministic configuration, not hidden LLM judgment.

No one signal is universal Authority.

### 11.3 Bounded output

Both limits are enforced:

- `max_items`
- `max_estimated_tokens`

The Store must not return unbounded conversation/memory history to downstream LLMs.

Stable tie-breaking is required for deterministic tests.

---

## 12. MemoryEvidenceView

Downstream modules receive immutable read-only evidence views, not repository objects.

Minimum item shape:

```text
MemoryEvidenceItem
- memory_id
- kind
- content
- provenance
- confidence
- freshness
- temporal_scope
- lifecycle
- contradiction_refs[]
- retrieval_score_components
```

Envelope:

```text
MemoryEvidenceView
- query_id
- generated_at
- items[]
- truncated
- degraded
- degradation_reasons[]
```

Consumers must be able to distinguish:
- historical evidence
- stale evidence
- conflicted evidence
- current authoritative facts supplied by other modules

Memory evidence must never hide this distinction by flattening everything into one plain-text summary.

---

## 13. Persistence / index ports

### MemoryRepositoryPort

Owns persistence mechanism behind the Domain boundary.

Required capabilities:
- read by id/revision
- atomic create/update with expected revision
- relation persistence
- bounded candidate listing/filtering
- lifecycle preservation

Repository implementation may be in-memory, PostgreSQL, or another provider. Provider-specific types do not enter Domain contracts.

### MemorySemanticIndexPort

Optional derived search/index capability.

- add/update/remove index entries
- semantic similarity retrieval
- provider-specific embedding/vector types stay outside Domain

The semantic index is **not canonical Memory state**.

If index update fails after canonical store commit:
- canonical Memory remains valid
- index state is marked degraded/pending repair
- do not roll back an already committed canonical Memory solely because a derived index failed

If the semantic index is unavailable, exact/filter/recency retrieval may continue in degraded mode where safe.

---

## 14. Concurrency / revision

Memory writes must not use a Core-global lock.

- record/relation mutation uses atomic expected-revision semantics
- independent Memory writes may proceed independently
- slow persistence/index operation must not block unrelated Brain/Body/Speech lanes
- Reflection #364 may be cancelled/deferred without blocking foreground retrieval
- stale write loses to current canonical revision
- retrieval observes a coherent snapshot/version or clearly reports partial/degraded state

A delayed Memory operation must not mutate current Emotion/Goal/Attention as a side effect.

---

## 15. Degraded operation

### Repository unavailable

Durable write returns typed failure/degraded result. It must not pretend persistence succeeded.

Depending on policy, ephemeral working context may continue in-memory without claiming durable persistence.

### Semantic index unavailable

Canonical record access continues where possible. Retrieval returns `degraded=true` with safe degradation reasons.

### Partial failure

Canonical repository and derived semantic index must have explicit recovery/rebuild semantics. Hidden divergence is not accepted as success.

---

## 16. Security / privacy boundary

#332 must not log or duplicate unbounded raw conversations merely for diagnostics.

- secret/provider credentials never enter Memory content or diagnostics
- provider raw objects are not Domain records
- diagnostic logs use IDs/counts/status/reason codes where possible
- retention/privacy policy can further restrict persistence without changing Memory semantic authority

---

## 17. Initial implementation scope

#332 initial implementation SHOULD include:

1. typed contracts/enums
2. deterministic Memory authority / reconciliation service
3. in-memory repository reference implementation for Unit/Adjacent tests
4. repository Port
5. optional semantic-index Port contract with fake implementation
6. bounded deterministic retrieval/ranking
7. immutable `MemoryEvidenceView`
8. typed degradation/failure results

Initial #332 MUST NOT require:
- PostgreSQL deployment
- production embedding provider
- Reflection LLM #364
- whole-app startup
- Character/TTS/Body

Infrastructure persistence/provider implementations can be added through their own Infrastructure ownership without changing #332 Domain semantics.

---

## 18. Required tests

### Store / validation

- store new valid candidate
- malformed candidate reject
- provenance-required durable candidate without provenance reject
- exact duplicate does not create unbounded records
- duplicate with new provenance merges provenance without losing old source
- stale expected revision reject
- invalid lifecycle transition reject

### Update / contradiction

- newer typed replacement can supersede while old record remains historical
- unresolved contradiction preserves both records and links them
- contradiction never auto-selects winner by recency alone
- semantic similarity alone cannot trigger merge/supersede

### Authority boundaries

- Memory does not mutate current Internal State
- Memory does not mutate current Goal/Commitment
- Relationship Memory does not directly set current Relationship
- prepared speech cannot be stored as “actually spoken” without actual presentation evidence
- planned Activity cannot be stored as executed Activity without #329 fact evidence

### Retrieval

- kind/ref/time filters
- deterministic ranking
- item budget
- estimated-token budget
- stale/conflicted metadata visible
- no unbounded history output
- stable tie-breaker

### Degradation / concurrency

- repository unavailable typed failure
- semantic index unavailable -> safe degraded retrieval
- canonical store success + index failure does not lose canonical record
- independent reads continue during slow optional index work

### Immutability / serialization

- returned evidence view cannot mutate canonical store through aliasing
- round-trip/serialization contract as applicable

---

## 19. Adjacent verification

After Unit PASS:

1. #326 ReferenceContext can consume bounded `MemoryEvidenceView` without Memory becoming NL semantic Authority.
2. #327 Appraisal can consume historical Memory evidence without restoring past current-state values.
3. #328 Executive can read bounded Memory evidence without Memory selecting Goal/Action.
4. #364 Reflection fixture can submit MemoryCandidate and receive typed Store disposition.
5. #366 Goal State remains independent from past Goal Memory.

Whole-app startup is not required for #332 completion.

---

## 20. Design acceptance

Design Gate PASS when implementation preserves all of the following:

- canonical Memory Store / Retrieval is non-LLM
- Reflection candidate generation is separate
- historical Memory does not override current Authority
- exact duplicate, refinement/supersession, and unresolved contradiction are distinct
- contradiction is preserved rather than silently erased
- semantic/vector similarity is evidence, not identity Authority
- prepared/intended work is not remembered as actual execution
- retrieval is bounded and provenance/freshness/conflict-aware
- DB/vector provider remains outside Domain
- provider degradation does not falsely claim success
- Memory work does not globally block unrelated runtime lanes

This document is the detailed canonical supplement for Issue #332.
## Memoryの明示semantic assertion（#664）

[Memory意味assertion公開契約](memory_semantic_assertion_contracts.md)を正本とする。candidate/recordのoptionalな明示facets、semantics込みのexact duplicate identity、EvidenceItemの元revisionと容量計上、順序を保持するfail-closed projection、current record/relationのexact read、旧保存形式のNone復元を同じ#332 Owner内で提供する。Speech投影と#364の意味判断は本Ownerから変更しない。

#664のfinalizable publicationはMemory ID単位のRepository同期境界とgenerationを使用する。current record/relationを同じ境界で読み、全mutationで局所tokenを失効させる。独立Memory更新と非待機Fence、登録writer/storage境界の詳細は上記正本に従う。

## #672：主体identityの保存・公開

[Memory意味assertion公開契約](memory_semantic_assertion_contracts.md)の#672節を本契約のtyped主体metadata正本とする。
ValidatedMemoryCandidate / MemoryRecord / MemoryEvidenceItemへ末尾optional subject_identityを保持し、MemorySemanticAssertionでは解決済み値だけを公開する。
MemoryContentとto_dictは変更しない。非null identityは共有型であり、content.subject_refとexact一致を必須とする。
重複判定へsubject_identityを含め、Noneとtyped値を別identityとして保存する。通常write・related write・Evidence・assertionへexact搬送し、provenance mergeで書き換えない。
旧payloadの欠落fieldはNoneとして読み、silent migration・backfillを行わない。physical DB schemaとstorage_schema_versionは保持する。
raw refの検索filterとrankingは不変、容量にはtyped metadataを含める。Runtime Character照合やraw refからのkind生成はMemory Ownerの責務にしない。
Reflection v2のwireを保持し、typed subject未供給の記録は保存可能だがassertionにはSUBJECT_UNRESOLVEDとなる。production供給は#673へ残す。


## Speech sourceからのpublic取得（#677）

Speechへ公開する範囲は既存bounded retrieval等によってExecutive contextへ採用されたMEMORY_EVIDENCEに限定する。source route登録を理由にDB全件を公開せず、ランキング・意味・lifecycleのAuthorityを変更しない。採用済みID/revisionのsemantic assertion publicationはCoreMemoryPersistenceBindingの非同期public境界から取得し、Memoryのassertionと元Owner tokenをexact保持する。具体的IDの追加/撤回registryは持たず、supersedeや消失は元Ownerの現在公開で検出する。Speech側の取得・失敗規則はspeech_semantics_contracts.md §11.15に従う。

## 25. 検索集合の現在公開（#686）

`MemoryStoreAuthority.read_retrieval_publication(query)`は既存の`retrieve(query)`と同じbounded `RankedMemoryEvidenceView`を`AuthorityReadPublication`として返す。consumerが検索集合の正本・generation・ledgerを所有してはならない。既存retrieveのranking、tie-break、max_items、max_estimated_tokens、truncated、diagnostics、degradedの意味は変更しない。

### 検索集合とID公開の分担

検索集合のparticipantは読取ごとに作成し、queryの構造的な候補範囲（kind、subject、temporal scope、observed期間）を同期metadataとして登録する。空集合、切詰めで表示されなかった候補、assertion未解決・inactive・conflicted等の現在除外される候補も保護対象に含める。条件が同じ候補範囲に対する更新は保守的に失効させる。semantic indexを使わない検索は範囲外のMemoryだけの更新では失効させない。semantic検索の依存範囲は下記のindex全体のtop-N契約に従い、構造filter外を無関係とは扱わない。全検索・全Owner共通のMemory generationを追加しない。publication/tokenの保持終了後は弱参照の登録を回収し、検索結果そのものを別ledgerへ保存しない。

#664のID別participant（rank 55）はexact identity/revisionのassertion現在性を引き続き所有する。検索集合participantはrank 56で、何が検索候補になるべきかを所有する。利用不能entryのID publicationがtokens=()である既存契約を変更せず、検索集合tokenがeligibilityの両方向の変化を捕捉する。利用可能なassertionのID tokenを検索集合tokenで代替してはならない。

### mutationと読取の同期

登録Repositoryのmutationは従来どおり対象IDを全順序で取得した後、同じID境界で旧recordと提案recordの構造的範囲を読む。relationは両端を対象とする。旧・新のいずれかがquery候補範囲に入れば、その検索participantを全順序で取得し、generationを進めてから既存保存処理を行う。commit/rollback完了まで保持する。失敗・同値更新も保守的に失効する。

registryの短いlockは登録・保留mutation範囲の更新だけに使い、participant待機・DB I/O中には保持しない。mutationの対象範囲を登録してから既存検索participantを取得する。取得中・保存中に新しいmatching queryが到着したら、既存のPARTICIPANT_BUSYで拒否し、検査対象から漏らさない。無関係なquery登録は許可する。読取は自分の検索participantを保持して既存retrieveを実行し、tokenを同じ境界から公開する。

削除・purgeの意味は従来どおり保存・retentionの責務であり、新しい削除方針を本Workで発明しない。登録writerが削除する場合も、ID別mutationと旧recordを渡す`retrieval_mutation`境界を通す必要がある。lifecycle・supersede・relation・主体・semantics・ranking入力の変更も同じ境界で検出する。直接SQL、登録境界を迂回するwriter、別processは#664同様に保証対象外である。

### ranking方針と派生index

ranking policyは既存MemoryStoreAuthorityが所有し、そのupdate入口をrank 57の局所participantへ参加させる。検索publicationには同じAuthorityのpolicy tokenを加える。policyの変更はそのpolicyに依存する検索を失効させるが、他Authorityや独立Memoryのwriteを直列化しない。

semantic検索は既存の `related_scores(semantic_query, limit=max_items)` が返すindex全体のtop-Nを使い、その後にMemoryの構造filterを適用する（方針B）。構造filter外のrecordでもtop-N内の候補を押し出してranking結果へ影響する。このため、semantic検索に「構造範囲外の更新では必ず失効しない」という保証は適用しない。構造scopeをindexへ渡す方針Aは既存Portとranking入力の意味を変えるため、本修正では採用しない。局所性の適用範囲を実際の依存に一致させる。index全体の世代はそのindexを利用するsemantic検索だけの依存であり、非semantic検索・別indexの検索・他Ownerの判断を全て失効させるMemory全体の世代ではない。

semantic indexを使う現在公開には、Memory Domainの`FinalizableMemorySemanticIndex`を明示登録する。wrapperは一つのstorage namespaceへ結び付け、同じnamespaceの登録Repository mutationを観測する。raw indexを自動で安全とみなさず、未登録indexによる現在公開はPARTICIPANT_UNSUPPORTEDとする。wrapper外のindex更新・直接SQL・別processは保証対象外。

### index同期状態と修復

§13の同期状態はこのwrapperがtypedに所有する。`MemorySemanticIndexState`はCURRENT、UPDATE_PENDING、DEGRADEDとする。登録直後は既存indexが正本と同期している証拠がないためDEGRADEDとし、明示的な`rebuild()`を必要とする。単なるrelated_scores成功や通常のupsert成功で障害状態を自動回復しない。

登録Repositoryの検索集合mutation開始時に、対象IDの同期metadataをdirtyとし、保留markerを登録してindex generationを進める。これはcanonical commitより前である。commit/rollback後にmarkerを回収するが、dirtyはindex同期が完了するまで残す。登録writerの削除も同じ境界を通す。relationは両端、supersedeは新旧recordを対象とする。同じnamespaceの別Repositoryからの変更も漏らさない。

index upsertは対象IDごとに順序付けし、現在の正本recordと入力recordの一致を確認する。完了までUPDATE_PENDINGで、provider I/O中に新しいcanonical mutationが入った場合は開始時のdirty世代と照合して古い完了でdirtyを消さない。別IDのDB writeをindex共通lockで直列化しない。古い入力・provider failure・未同期の完了はrepair-requiredを保持する。正本保存結果は撤回せず、writeには既存SEMANTIC_INDEX_UPDATE_FAILEDを返す。保存を経由しない直接のupsertも、登録正本との照合を省略しない。

CURRENTは保留canonical mutation、実行中のindex操作、dirty ID、repair-requiredが全てない場合だけである。UPDATE_PENDINGのsemantic現在公開はPARTICIPANT_BUSY、DEGRADEDはPARTICIPANT_UNAVAILABLEとしてtokenを発行しない。通常のretrieveは既存SEMANTIC_INDEX_UNAVAILABLEのdegraded経路を使用する。非semanticのexact/filter/recency検索とその局所tokenは継続する。

修復は、追加の`RebuildableMemorySemanticIndexPort.rebuild(records)`能力を持つproviderへの明示入口だけとする。元のMemorySemanticIndexPortは変更しない。正本snapshotを取得して派生indexを全置換し、削除済みentryも除く。provider I/O中は共通participantを保持しない。並行canonical mutationがなかったこと、rebuild成功、実行中upsertがないことを確認して初めてdirtyとrepair-requiredを解除する。mutationと競合したrebuildはDEGRADEDのままで明示再試行が必要。rebuild中の通常upsertは待機させず失敗として扱い、canonical writeは維持する。修復能力がないproviderはCURRENTへ昇格させない。

policy tokenを先に取得し、検索集合participantの境界でindexのCURRENTとtokenを短く取得してからretrieveを行う。index tokenは読取前の世代を保持し、I/O後に新世代へ取り直さない。途中のindex変更は最終Fenceのgeneration不一致で拒否する。途中のpolicy更新は既存freshness検査または最終Fenceで拒否する。degraded viewの内容は保持するがtokenは返さない。

### Fence・資源・構成境界

ID 55 → 検索集合56 → policy57 → index58の全順序に従う。index58は状態・世代・markerの短い更新にだけ保持し、DB/index I/Oには保持しない。registry lockを保持したままindex58へ入らない。indexのID別I/O順序付けlockを取得したままID55・検索集合56を取得しない。Fence自身ではDB読取・ranking・遅いI/Oを行わず、既存の非待機取得によるBUSY・generation mismatchで拒否する。検索readやmatching writeの遅さを、無関係なquery/IDへ新しい全体lockで伝播させない。SQLite等の既存storage制約を緩和したとは主張しない。

検索集合1＋policy1（semantic index使用時はさらに1）に、必要なID token・他Owner・targetを加え、既存16 participant上限で検査する。上限超過時にtokenを落としたり上限を拡張したりしない。

PostgreSQLの同一storage namespaceのRepository間では既存#664 registryを共有し、検索participantも同じregistryで同期する。Persistence runtimeとCoreMemoryPersistenceBindingは既存executor・受付上限・取消後回収・停止処理から現在公開を提供する。新executorや別MemoryStoreを作らない。#614のconsumer wiringは本Workで変更しない。
