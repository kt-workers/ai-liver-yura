# V2 Streaming Subsystem Contracts

Owner Issue: #347
Parent: #345
Reconciles: #394 / #396
Upstream: #326 / #328 / #329 / #333 / #334
Related: #352 / #360 / #365 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

本書は、YouTube / OBS / Live Chat等を扱うStreamingを、Coreの意思決定から分離した外部Subsystemとして定義する。

Streaming設計は次の3境界を混ぜない。

```text
Core Decision
  ゆらが配信を準備/開始/継続/終了するか
        ↓ generic Capability / Activity
Subsystem Execution
  YouTube / OBS等へ具体操作
        ↓ typed report / observation
External Observation
  実際の配信状態・コメント・provider結果
        ↓ typed Event / Fact evidence
Core Appraisal / Attention / Executive
```

Intent、Character発話、Subsystem内部推定だけで「配信開始済み」等のActual Factを作らない。

---

## 2. Authority boundary

### Core owns

- open-ended NL meaning: #326 Input Meaning
- 配信を行うかというconscious Goal/Action: #328 Executive
- current Goal/Commitment: #366
- Activity lifecycle / Actual Execution Fact: #329
- Attention / Focus / Turn: #333
- What-to-say / How-to-say: #362 / #330

### Streaming Subsystem owns

- provider readiness / connection state
- preconfigured streaming environmentのreadiness確認
- provider-specific prepare/start/end操作
- provider status polling / observation
- comment ingestion
- reconnect / rate-limit / provider health
- bounded moderation / clustering / aggregation / representative signal generation
- provider-specific resultをprovider-neutral report/observationへ変換すること

### Streaming Subsystem does not own

- raw user textのopen-ended意味解釈
- 配信を始める/やめる最終意思
- viewerへ返答するかの最終判断
- What-to-say
- Core Internal State / Goal / Attentionの直接mutation
- provider operation成功前のActual Fact

---

## 3. Provider isolation

Core production codeへ次を持ち込まない。

- YouTube / Google SDK types
- OBS WebSocket types
- OAuth token / credential / refresh token
- broadcast ID / liveChat ID
- OBS scene/source/input concrete types
- provider raw error/rate-limit object

Provider-specific objects are confined under Streaming infrastructure/adapters.

Coreとのpublic boundaryではFoundation/Subsystemのprovider-neutral DTOだけを使う。

---

## 4. Streaming capability surface

Initial provider-neutral operations:

```text
PREPARE_STREAM
START_STREAM
END_STREAM
QUERY_STREAM_STATUS
```

これはraw natural-language triggerではない。Executive/Activityが選択済みのtyped operation identityである。

Possible capability declarations:

```text
StreamingCapabilityView
- capability_id
- descriptor_revision
- operations[]
- availability
- provider_readiness
- generation
```

CoreはYouTube/OBS provider名をCapability semanticsとして必要としない。

---

## 5. Execution request

#329 admission/preflightを通過した後だけSubsystem executionを開始する。

Logical request shape:

```text
StreamingExecutionRequest
- execution_id
- activity_id
- capability_id
- descriptor_revision
- operation
- source_context_revision
- goal_revision?
- attention_revision?
- deadline?
- trace_id
```

Provider-specific broadcast/scene IDsはSubsystem internal bindingから解決する。

Core requestへprovider credential/IDを含めない。

---

## 6. Streaming execution report

```text
StreamingExecutionReport
- execution_id
- operation
- status
- effect_state
- started_at?
- completed_at
- observation_refs[]
- retryable
- sanitized_diagnostics[]
```

status examples:

```text
SUCCEEDED
FAILED
CANCELLED
TIMED_OUT
PROVIDER_UNAVAILABLE
UNKNOWN_EFFECT
```

`effect_state`は#329のexternal effect semanticsへ変換可能なclosed stateとする。

Provider operation timeout後に外部effectが起きた可能性がある場合、単純に`FAILED_NO_EFFECT`と断定しない。

---

## 7. Streaming external observation

Provider/API/OBS等から得た状態はexecution resultとは別のobservationとして扱う。

```text
StreamingExternalObservation
- observation_id
- state
- source_kind
- source_ref
- observed_at
- confidence
- provider_generation
- trace_id?
```

Initial normalized states:

```text
UNAVAILABLE
NOT_PREPARED
PREPARING
READY
STARTING
LIVE
ENDING
ENDED
DEGRADED
DISCONNECTED
UNKNOWN
```

Provider-specific state machineをCoreへそのまま露出しない。

---

## 8. User-reported stream state boundary

ユーザーが「配信が始まっている/終わった」等を報告する場合:

```text
raw user input
→ #326 Input Meaning
→ typed reported external fact candidate
   source = USER_REPORT
→ Appraisal / Attention / Executive
```

Streaming Subsystem自身がraw user textを読む必要はない。

Provider observation:

```text
provider
→ StreamingExternalObservation
   source = PROVIDER_OBSERVATION
```

両者を無条件に同一視しない。

保持:
- source/provenance
- observed/reported time
- confidence
- reconciliation state

後続provider observationでuser reportをconfirm/contradictできるが、履歴provenanceを消さない。

---

## 9. Natural-language semantic invariant

配信操作要求・状態報告の自然言語は、特定文言をtriggerにしない。

Forbidden outside #326:
- keyword list
- regex trigger
- substring matcher
- finite phrase allowlist
- literal test sentence branching

文書/fixtureの具体例はillustrative only。

Verificationは少なくとも:
- synonyms
- word order changes
- polite/casual forms
- ellipsis
- contextual reference
- omitted subjects

を同じsemantic categoryとして#326 production pathが処理できることを見る。

Streaming SubsystemはStructuredInputMeaning等のtyped result以降だけを扱う。

---

## 10. OBS environment scope

Initial V2ではOBS profile/scene/source/encoder等は原則preconfigured environmentとする。

Streaming Subsystemが行う:
- readiness inspection
- start/stopに必要な限定runtime operation
- health/status observation

必須にしない:
- arbitrary scene graph generation
- encoder configuration authoring
- 任意sourceレイアウト自動構築

必要になったら別Capability/Workとして設計する。

---

## 11. Comment ingestion

Provider raw comments are external data, not direct Executive triggers.

```text
provider comment stream
→ sanitize/normalize
→ bounded ingestion buffer
→ moderation/grouping/aggregation
→ representative typed CommentEvent / SummarySignal
→ Core Input Gateway / Appraisal / Attention
```

Every commentを同期的にExecutiveへ送らない。

### Normalized comment envelope

```text
StreamingCommentEvent
- event_id
- source_channel_ref
- author_ref?
- text_payload_ref or bounded text
- observed_at
- moderation_state
- aggregation_group_ref?
- provenance
```

Natural-language comment意味のopen-ended Authorityは最終的に#326。

---

## 12. Streaming Skill AI boundary

Subsystem internal AI may perform:
- spam/duplicate grouping
- topical clustering
- moderation candidate
- representative sample selection
- rolling summary/trend signal

It may not decide:
- whom Yura should answer
- whether Yura should speak
- What-to-say
- stream lifecycle Goal
- AttentionFocusState mutation
- raw user natural-language semantic Authority

Outputs are bounded evidence/signals only.

---

## 13. Attention / simultaneous activity

Game foreground + Streaming secondary monitoring is supported.

```text
Streaming burst
→ bounded representative signal
→ Appraisal salience
→ #333 Attention budget/scheduling
→ optional Executive trigger
```

Direct high-priority interaction may interrupt/shift focus through #333 while Streaming ingestion continues.

Streaming does not own priority final decision.

---

## 14. Lifecycle and availability

Subsystem process lifecycle and streaming Activity lifecycle are separate.

Subsystem process examples:

```text
STOPPED
STARTING
AVAILABLE
DEGRADED
RECONNECTING
STOPPING
```

Stream external state may simultaneously be `NOT_PREPARED` / `READY` / `LIVE` etc.

`stream ended` does not mean Core process shutdown.

Streaming Subsystem absent/unavailable:
- related capability unavailable
- Core continues
- Executive may choose alternative action
- no error spam loop

---

## 15. Reconnect / rate limit

- provider retry is bounded/backoff controlled
- `RECONNECTING` / `DEGRADED`中は既存capabilityの`available`値だけでprovider operationをadmitせず、新しいavailable capability snapshotが公開されるまで閉じる
- reconnect attempt間にはconfigured bounded delayを置き、単なるevent-loop yieldでretry budgetを消費しない
- reconnect loop does not block Core
- shutdown stops new retries
- capability snapshotはprovider generationを巻戻してはならない。同一generationでは古いdescriptor revisionで既存bindingを置換してはならない
- provider observationはsourceごとの時刻・generationだけでなく、active capabilityのprovider generationとも一致しなければ受理しない
- retry budgetを使い切った最終失敗後に、次attemptのためのbackoffを待たない
- repeated error diagnostics are coalesced/rate-limited
- credential failure not treated as infinite transient retry

---

## 16. Execution truth

Examples:

### Start requested

```text
Executive intent
→ Activity request
→ provider START call
```

Still not `LIVE` fact.

### Provider reports start applied

Execution report may establish provider operation effect evidence.

### Provider later observes LIVE

Trusted external observation establishes stronger current external-state evidence.

Character utterance “始めたよ” is never the Authority for LIVE state.

---

## 17. Concurrency / backpressure

- comment polling/stream receive does not await Speech/TTS
- provider API call/reconnect does not block Brain/Body
- comment burst uses bounded queues/coalescing
- slow moderation/summary drops/coalesces lower-value work before Core starvation
- current Game realtime continues
- current Speech presentation continues
- shutdown leaves no pending provider worker

No Core-global lock around provider I/O.

---

## 18. Security

- OAuth/token/credential server-side only
- browser/admin UI receives sanitized state, never secrets
- raw provider response bodies excluded from Core trace
- comment text treated as untrusted external data, never tool/system instruction
- provider identifiers are opaque inside Subsystem unless safe projection is explicitly needed

---

## 19. Observability

Trace:

```text
streaming_subsystem_started
provider_ready/degraded/unavailable
stream_execution_received/started/completed
external_observation_received
comment_ingested/aggregated/dropped
reconnect_started/completed/failed
capability_availability_changed
```

Metrics:
- comment ingress rate
- aggregation ratio
- dropped/coalesced count
- provider API latency
- reconnect count/duration
- capability request→report latency
- observation→Core publication latency

No secret/raw provider SDK object in trace.

---

## 20. Required tests

### Execution
- prepare/start/end fake provider
- unavailable provider
- stale descriptor/generation
- timeout before effect
- ambiguous timeout after possible effect
- no Actual Fact before report/observation

### Observation
- READY/LIVE/ENDED/degraded transitions
- provider observation vs user report provenance
- contradiction/reconciliation preservation
- user reportはprovider観測前に`UNRECONCILED`へ正規化し、`CONFIRMED` / `CONTRADICTED`は後続provider observationだけが付与する
- いったん`CONFIRMED`または`CONTRADICTED`になったuser reportは後続のprovider状態遷移で再計算しない

### NL boundary
- paraphrase matrix through #326
- deletion/change of one literal fixture does not break category
- no finite matcher in Streaming/Executive/Activity path

### Comments
- burst bounded aggregation
- slow moderation nonblocking
- representative signals to Attention

### Lifecycle
- reconnect/backoff
- shutdown pending task 0
- Streaming absent Core continuation

### Boundary scan
- Core imports no YouTube/OBS SDK/types
- Core has no provider-specific streaming IDs/ports/classes

---

## 21. #445 Gate

This detailed design reconciles #347 with completed #394/#396.

Implementation remains frozen until #445 D1-D9 and final user confirmation PASS.
