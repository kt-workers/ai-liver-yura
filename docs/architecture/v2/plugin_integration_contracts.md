# V2 Plugin Integration Contracts

Owner Issue: #344
Parent: #342
Upstream: #321 / #322 / #328 / #329 / #343
Related: #334 / #345 / #365 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

本書は、Plugin 0件でもCore基本責務が成立し、Plugin追加時にはCore公開契約からCapabilityだけが増えることを、Core Authorityを侵食せずに結合するIntegration契約を定義する。

```text
Trusted composition
  ├─ zero plugin
  │    ↓
  │  empty PluginRegistrySnapshot
  │    ↓
  │  Core continues normally
  │
  └─ one or more plugins
       ↓ typed manifest + host permission grants
     #343 Plugin Registry
       ↓ CapabilityDescriptor snapshot
     Executive / Planner read-only capability facts
       ↓ selected high-level intent
     #329 Activity Execution
       ↓ bound capability + second preflight
     Plugin capability adapter
       ↓ ExecutionAdapterReport / effect evidence
     #329 Actual Execution Fact Authority
```

#344は新しいGoal / Meaning / Activity / Plugin lifecycle Authorityを作らない。

---

## 2. Zero-plugin system invariant

Plugin Registryが空でも、Core bootは正常である。

必須:
- Registry snapshotはvalid empty collectionを返す。
- Capability discovery結果0件は例外ではない。
- Input Meaning / Appraisal / Executive / Goal / Speech / BodyのCore native responsibilityは起動可能。
- Plugin absentをframe/turnごとにwarning spamしない。
- Body / TTS Provider / Persistence / Streaming / AvatarをPluginとして補完しない。
- Pluginが必要なActivityだけが`CAPABILITY_UNAVAILABLE`等のtyped resultへ縮退する。

Plugin 0件Core成立はSystem invariantであり、「Pluginとはなくても動く機能」という定義にはしない。

---

## 3. Composition boundary

Trusted Composition Rootだけが次を#343へ提供する。

```text
PluginCompositionInput
- discovered_manifests[]
- permission_grant_snapshot
- lifecycle_adapter_bindings[]
- capability_execution_bindings[]
- generation_context
```

禁止:
- Manifest本文をPython import pathとして無検証実行する。
- Plugin自身がpermission grantを作る。
- Browser/GUIからcredential付きPlugin objectをCoreへ直接注入する。
- raw user textをPlugin discovery/routingに使う。

Manifest validation完了前にPlugin code lifecycleを開始しない。

---

## 4. Registration to Capability discovery

#343 lifecycle/permission/healthのclosed rulesからFoundation `CapabilityDescriptor`を投影する。

Consumersが見るのはread-only current snapshotだけ。

```text
PluginRegistrySnapshot
→ CapabilityDescriptor[]
→ ExecutiveContextSnapshot / Planner capability view / #329 preflight
```

Integration rule:
- Registry internal objectをExecutiveへ渡さない。
- capability IDだけでなくdescriptor revisionを保持する。
- availability変化でdescriptor revisionが進む。
- stale `CapabilityBinding(capability_id, descriptor_revision)`は#329 second preflightで拒否する。
- Registryは「どのCapabilityを使うべきか」というGoal/Action選択をしない。

---

## 5. Capability execution path

Plugin capability invocationは必ず#329 Activity Execution contractを通る。

```text
Committed Executive / Activity request
→ #329 admission
→ CapabilityRequirement resolution
→ CapabilityBinding(capability_id, descriptor_revision)
→ preflight
→ PluginCapabilityExecutionPort.invoke(...)
→ ExecutionAdapterReport
→ #329 post-effect reconciliation
→ Actual Execution Fact
```

#344はPlugin用のparallel Execution Fact Authorityを作らない。

### PluginCapabilityExecutionPort

Integration boundaryとしてprovider-neutral interfaceを要求する。

```text
PluginCapabilityExecutionRequest
- execution_id
- activity_id
- capability_id
- descriptor_revision
- operation_id
- typed_input
- deadline?
- cancellation_token_ref?
- trace_id

PluginCapabilityExecutionReport
- execution_id
- capability_id
- descriptor_revision
- operation_id
- status
- typed_output?
- effect_evidence[]
- started_at?
- completed_at
- sanitized_diagnostics[]
```

実際のproduction typeは#329 Foundation/Activity contractを再利用し、Plugin専用で同じ概念を重複定義しない。上記はintegration上必要なidentityを示す論理shapeである。

---

## 6. External effect fence

Plugin operationにはside effect declarationがあるが、宣言は実際にeffectが起きた証明ではない。

### Before effect

- capability unavailable
- permission revoked
- stale descriptor
- deadline exceeded
- cancelled before invocation

なら、外部効果なしのtyped failureとして終了可能。

### After effect may have occurred

Provider call中のnetwork timeout/cancel等で、外部効果が起きた可能性がある場合:

- `cancelled`だけで「何も起きなかった」と確定しない。
- report/effect evidenceを`UNKNOWN / POSSIBLY_APPLIED / APPLIED`等の#329 closed effect semanticsへ投影する。
- retryにより二重effectを起こす可能性を扱う。
- idempotency keyをproviderが支援する場合はAdapter内部で利用可能だが、Plugin RegistryがActual Factを決めない。

Intent/Plan/Character claimから外部effect successを作らない。

---

## 7. Permission revocation race

Permission revocation時:

1. #343がnew Capability discovery availabilityを先に閉じる。
2. new #329 preflightはrejectする。
3. already-started executionは、そのoperationのcancellation support / side-effect stateに従う。
4. 既に起きたeffect evidenceは削除しない。
5. late reportはexecution identity/generationを照合し、別generationへ適用しない。

Permission revokeを過去のExecution Fact削除へ使わない。

---

## 8. Health / lifecycle race

`STOPPING` fenceが開始したPluginをhealth reportだけでAVAILABLEへ復帰させない。

Plugin stop sequence:

```text
close new availability
→ reject new execution admission
→ cancel/finish supported in-flight operations
→ lifecycle adapter stop
→ STOPPED
→ optional UNREGISTERED
```

slow lifecycle I/O中にRegistry atomic lockを保持しない。

Core Body/Speech/Game等のunrelated laneをstop I/Oでblockしない。

---

## 9. Plugin generation / re-add

Pluginをunregister後に同じ`plugin_id`で再登録した場合はnew generationとして扱う。

- old health reportをnew generationへ適用しない。
- old execution reportをnew generationのcapability stateへ混ぜない。
- capability revision tombstone floorを維持しrevisionを巻き戻さない。
- in-flight old generation effect evidenceはhistorical executionとして保持する。

---

## 10. Plugin vs Provider vs Subsystem classification

### Plugin

Core公開extension contractから新Capabilityを追加する。

### Infrastructure Provider

Coreが既に要求するPort（LLM/TTS/Persistence等）の具体実装。

Providerを「交換可能/外部だから」という理由でPluginと呼ばない。

### Subsystem / Skill Runtime

独立process/realtime loop/専門AI/大規模external lifecycleを持つシステム。

SubsystemがCoreへCapabilityを公開するためPlugin-like registration surfaceを利用する可能性はあるが、Subsystem全体をPlugin Registry lifecycleへ押し込まない。具体境界は各Subsystem designが所有する。

Game Skill #365のframe loopはPlugin execution callのawait列へ従属させない。

---

## 11. Authority isolation tests

Pluginは以下を直接変更できないことをIntegrationで確認する。

- Internal State
- Goal / Commitment
- Attention / Focus
- Character Definition/Profile
- SpeechSemanticPlan
- BodyState / BodyIntent
- Memory canonical Store
- Actual Execution Fact

Plugin reportはtyped evidence/eventとしてownerへ戻るだけ。

Plugin AIが存在してもExecutive Goal Authorityを持たない。

---

## 12. Concurrency / backpressure

- slow Plugin executionはunrelated Core laneをblockしない。
- per-execution deadline/cancelは#322/#329に従う。
- Pluginごと/Capabilityごとのbounded in-flight policyをcompositionで設定可能。
- provider callback/event burstはbounded event projectionを通す。
- Plugin failure stormでdiagnostic spam/queue explosionを起こさない。
- foreground Activityがbackground Plugin activityでstarveされない。

#344は新しいglobal async lockを導入しない。

---

## 13. Degraded / unavailable behavior

Plugin absent/unavailable時:

- CapabilityDescriptor availabilityを通してExecutive/Planner/#329へ事実を公開する。
- generic fixed phrase responseをPlugin layerが生成しない。
- unavailable capabilityに依存するGoal/Activityの次判断はExecutiveへ戻す。
- Core全体shutdownを起こさない。

Plugin output schema mismatch / invalid reportはfail-closedで、そのreportからActual Factを作らない。

---

## 14. Integration observability

Trace events:

```text
plugin_discovered
plugin_validated
plugin_registered
plugin_available/degraded/unavailable
permission_changed
capability_descriptor_published
activity_capability_bound
plugin_execution_started/completed/failed/cancelled
plugin_effect_observed/unknown
plugin_stopping/stopped/unregistered
```

Correlation:
- plugin_id
- plugin_generation
- capability_id
- descriptor_revision
- activity_id / execution_id
- operation_id
- trace_id

secret / raw credential / raw provider responseをtraceへ出さない。

---

## 15. Fake integration topology

### Zero plugin

- empty Registry
- Core minimum text path
- no capabilities
- Plugin absence warning stormなし

### One fake plugin

Fake manifest:
- one capability
- one operation
- explicit permission
- controllable health
- controllable external effect report

Verify:
1. valid register → descriptor publication
2. Executive/read-only discovery
3. #329 binding / second preflight
4. invoke / report / Actual Fact projection
5. health degradation
6. permission revoke before start
7. revoke after effect
8. stale descriptor
9. stop during execution
10. unregister/re-add generation fencing
11. timeout/cancel before effect
12. ambiguous after-effect timeout
13. Core unrelated lane continuation

---

## 16. Completion acceptance

#344 Design acceptance:
- zero-plugin Core composition is first-class valid state
- Plugin adds Capability only through public contract
- execution goes through #329
- permission/lifecycle/health races are fenced
- stale descriptor/generation cannot be used
- already-applied effect is preserved
- Provider/Subsystem classification is not conflated
- slow/failing Plugin does not block unrelated Core
- no Core native Authority is writable by Plugin

Implementation remains frozen until #445 D1-D9 and final user confirmation PASS.
