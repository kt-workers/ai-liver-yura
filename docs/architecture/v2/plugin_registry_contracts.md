# V2 Plugin Registry / Manifest / Permission Contracts

Owner Issue: #343
Parent: #342
Upstream: #321 / #329
Downstream: #344 / Executive / Planner / Activity Execution
Related canonical:
- `docs/architecture/v2/plugin_architecture.md`
- `docs/architecture/v2/foundation_contracts.md`
- `docs/architecture/v2/activity_execution_contracts.md`
- `docs/architecture/v2/concurrency_architecture.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

#343 は、Core が公開する拡張境界から Plugin を発見・検証・登録し、利用可能な Capability を immutable な read model として公開する Registry / Lifecycle Authority を構築する。

Plugin は「なくても動くもの」という optionality だけでは定義しない。

> Plugin は Brain / Body 等の Core 自身の構成要素ではなく、Core の公開拡張契約を通して外部から新しい Capability を追加する機構である。

#343 は Plugin の意味判断や外部操作そのものを所有しない。Capability execution と Actual Execution Fact は #329 を通す。

```text
Discovery / Composition Adapter
        ↓ typed manifest
Plugin Registry #343
  ├─ manifest validation
  ├─ lifecycle state
  ├─ permission grant projection
  ├─ health / availability projection
  ├─ registry + capability revision
  └─ Foundation CapabilityDescriptor view
        ↓
Executive / Planner / #329 preflight
        ↓
#329 Activity Execution
        ↓
Plugin / Subsystem capability adapter
        ↓
ExecutionAdapterReport / Actual Execution Fact
```

---

## 2. Authority boundaries

### 2.1 #343 owns

- `PluginManifest` の typed contract と strict validation
- Plugin ID / version / contract version の整合
- Plugin lifecycle state
- Registry 内の Plugin / Capability identity index
- capability ID の global uniqueness
- permission requirement declaration と host grant の exact projection
- bounded health observation の採用
- effective Capability availability の決定論的投影
- monotonically increasing registry revision
- monotonically increasing CapabilityDescriptor revision
- immutable Registry / Capability read model
- register / health update / stop / unregister の atomic state transition

### 2.2 #343 does not own

- raw user text の意味解析
- Executive Goal / Action selection
- Goal / Commitment State
- Internal State / Character / Body State
- Activity execution lifecycle / Actual Execution Fact
- Plugin 固有 SDK object / credential / transport
- dynamic import や任意 Plugin code execution
- per-request user authorization の意味判断
- Plugin provider の具体的 start/stop API
- Game frame-level skill logic
- Streaming / Avatar 等の Subsystem process state

Registry は「この Capability が現在公開可能か」を決めるが、「今この Capability を使うべきか」は決めない。

---

## 3. Existing Foundation Capability contract

#343 は #321 の `CapabilityDescriptor` / `CapabilityRequirement` を置き換えない。

既存 Foundation contract:

```text
CapabilityDescriptor
- capability_id
- capability_type
- operations[]
- availability
- revision
- attributes
```

#329 は `CapabilityRequirement(capability_type, operation, allow_degraded)` に対し Foundation `CapabilityDescriptor.satisfies()` を使用し、選択した `capability_id + descriptor_revision` を `CapabilityBinding` へ固定する。

したがって #343 は Plugin 固有 metadata を別の新しい Foundation 型へ押し込まず、Manifest / Registry の typed state から **Foundation `CapabilityDescriptor` を決定論的に投影**する。

- #329 の既存 binding / preflight contract を変更しない。
- permission 不足や Plugin health failure は effective `availability` に反映する。
- operation/schema/permission/lifecycle metadata が変化した場合は descriptor revision を必ず進める。
- `attributes` は Registry が定義する closed schema の projection とし、consumer が任意 JSON の自然言語意味を推測しない。

---

## 4. Manifest identity and versioning

### 4.1 PluginManifest

Domain の最低 contract:

```text
PluginManifest
- plugin_id
- plugin_version
- contract_version
- display_name
- capabilities[]: PluginCapabilityDeclaration
- required_permissions[]: PluginPermissionRef
- optional_dependencies[]: PluginDependencyRef
- resource_requirements[]: PluginResourceRequirement
- lifecycle_hooks[]: PluginLifecycleHook
```

### 4.2 plugin_id

- stable logical Plugin identity。
- Registry 内で同時に1世代だけ active にできる。
- file path / Python module / package import path を identity にしない。
- Provider/Adapter の class 名を identity semantics にしない。

### 4.3 plugin_version

Plugin implementation/content version。

- non-empty bounded version string。
- Registry v1 は version string の大小を意味解釈しない。
- 同じ `plugin_id + plugin_version` で immutable Manifest payload が異なる状態を silently accept しない。
- manifest content を変更する場合は version を進めるか、一度 unregister して新 generation として再登録する。

### 4.4 contract_version

Core Plugin contract の schema/semantics version。

- strict non-negative integer。
- v1 implementation が対応する contract version を明示 allowlist する。
- unsupported version は Plugin code を起動する前に fail-closed。
- `plugin_version` と `contract_version` を混同しない。

---

## 5. Capability declaration

### 5.1 PluginCapabilityDeclaration

```text
PluginCapabilityDeclaration
- capability_id
- capability_type
- operations[]: PluginOperationDeclaration
- required_permissions[]: PluginPermissionRef
- health_policy
- metadata_revision_seed?  # runtime revisionではない。通常不要
```

`capability_id` は Registry 全体で一意。

同じ `capability_type / operation` を複数 Plugin が提供すること自体は許可する。Foundation #329 は現在の CapabilitySnapshot から satisfying descriptor を選択する。Registry は provider preference や semantic routing Authority を追加しない。

### 5.2 PluginOperationDeclaration

```text
PluginOperationDeclaration
- operation_id
- input_schema_ref
- output_schema_ref
- side_effect_class
- required_permissions[]
- cancellation_support
- timeout_support
```

operation は provider-independent identifier とする。

禁止:
- raw natural-language trigger phrase
- regex / keyword matcher
- concrete SDK method object
- credential / token
- renderer / game-specific runtime object

### 5.3 Side effect class

初期 closed enum:

```text
NONE
OBSERVABLE_EXTERNAL
MUTATING_EXTERNAL
```

これは Actual Effect が発生したという Fact ではない。operation が持ち得る外部効果の性質を preflight / diagnostics へ伝える declaration である。

Actual Effect は #329 の `ExecutionEffectEvidence` / `ExecutionResult` でのみ確定する。

### 5.4 Cancellation support

初期 closed enum:

```text
NONE
SOFT
HARD
```

Plugin declaration は「Providerが何を支援できるか」を示すだけで、実際の command interruptibility は Executive / #329 の Authority を上書きしない。

### 5.5 Timeout support

```text
PluginTimeoutSupport
- supports_deadline: bool
- supports_provider_timeout: bool
```

Manifest が arbitrary timeout 秒数を Core Authority として決めない。実 request の deadline / timeout policy は #322 / #329 / composition policy が所有する。

---

## 6. Permission contract

### 6.1 Principle

Plugin は必要 permission を宣言できるが、自分自身へ permission を付与できない。

```text
Plugin manifest
  → required permission declaration
Trusted host/composition
  → PluginPermissionGrantSnapshot
Registry
  → exact match / effective availability
```

### 6.2 PluginPermissionRef

```text
PluginPermissionRef
- permission_id
- scope_ref?
```

- exact identifier comparison only。
- prefix / substring / regex / glob による暗黙拡張は禁止。
- `scope_ref=None` と specific scope は別 identity とする。

permission ID の例は設計説明であり、有限 allowlist の意味解析 engine を作らない。

例:
- read-only resource access
- external side effect
- filesystem write
- network access
- game controller output
- account operation

### 6.3 PluginPermissionGrantSnapshot

Host / deployment / user configuration 等の trusted owner から read-only で渡す。

```text
PluginPermissionGrantSnapshot
- grant_revision
- grants[]: PluginPermissionRef
- captured_at
```

Registry は grant source を所有しない。

### 6.4 Effective permission set

Capability の effective required permission は:

```text
manifest.required_permissions
∪ capability.required_permissions
∪ operation.required_permissions
```

全件 exact grant されていなければ、その operation を利用可能 operation として公開しない。

Capability 内に permission を満たす operation が1件も残らない場合、その capability は `UNAVAILABLE` とする。

Plugin は permission 不足を自身の health report で `AVAILABLE` に昇格できない。

### 6.5 Per-request authorization boundary

#343 の permission grant は install/runtime capability permission であり、「このユーザー/このcommandに今回許可するか」という per-request semantic authorization ではない。

Per-request Authority / precondition は `SystemCommand.authority` / `preconditions` と #329 preflight の責務を維持する。

---

## 7. Optional dependency / resource declarations

### 7.1 PluginDependencyRef

```text
PluginDependencyRef
- plugin_id
- contract_version?
```

#343 v1 の Manifest では optional dependency のみを扱う。

- absent でも registration 自体を block しない。
- dependency ID を import path として実行しない。
- cycle を Core execution dependency として自動生成しない。

必須 dependency graph が将来必要なら、別の explicit design を追加する。

### 7.2 PluginResourceRequirement

```text
PluginResourceRequirement
- resource_type
- amount
- unit
```

これは host scheduling / diagnostics の bounded declaration。

- GPU/CPU/provider固有 objectをDomainへ入れない。
- Registry v1 は resource amount から availability を勝手に推測しない。
- host resource policyが別途 unavailable を返した場合のみ typed inputとして反映する。

---

## 8. Lifecycle state machine

### 8.1 PluginLifecycleState

```text
DISCOVERED
→ VALIDATED
→ REGISTERED
→ AVAILABLE / DEGRADED / UNAVAILABLE
↔ AVAILABLE / DEGRADED / UNAVAILABLE
→ STOPPING
→ STOPPED
→ UNREGISTERED
```

### 8.2 Meaning

- `DISCOVERED`: manifest dataを受領しただけ。Capability公開なし。
- `VALIDATED`: schema/version/identity検証済み。Capability公開なし。
- `REGISTERED`: registry identity/indexをatomicに確保。まだhealth未確定ならCapabilityはUNKNOWN/UNAVAILABLE相当。
- `AVAILABLE`: health/permissionを含むeffective stateが利用可能。
- `DEGRADED`:明示的にdegraded useが可能な状態。
- `UNAVAILABLE`:登録済みだが新規executionへ提供不可。
- `STOPPING`:新規executionへ提供不可。stop処理中。
- `STOPPED`:provider側停止確認済み。Capability公開不可。
- `UNREGISTERED`:registry active indexから除外済み。tombstone revision floorは保持。

### 8.3 Illegal transitions

- DISCOVERED→AVAILABLE の直接遷移禁止。
- UNREGISTERED→AVAILABLE の直接復活禁止。
- STOPPING中にhealth reportだけでAVAILABLEへ戻さない。
- 同じmanifest/plugin generationに対する重複registerをidempotent success扱いしない。明示的 duplicate とする。

新たに add する場合は新 generation として DISCOVERED から開始する。

---

## 9. Health observation

### 9.1 PluginHealthState

```text
HEALTHY
DEGRADED
UNAVAILABLE
UNKNOWN
```

### 9.2 PluginHealthObservation

```text
PluginHealthObservation
- plugin_id
- plugin_generation
- observation_revision
- plugin_health
- capability_health[]
- observed_at
```

capability override:

```text
PluginCapabilityHealth
- capability_id
- health
```

Rules:
- unknown capability ref reject。
- duplicate capability health reject。
- old plugin generation observation reject。
- observation revision rollback reject。
- same observation revision + different payload = invariant violation。
- observed_at rollbackを silently latest にしない。

Health payloadのfree-form provider exception textをRegistry Stateへ保存しない。

---

## 10. Effective capability availability

Availability は Plugin 自己申告をそのまま採用せず、Registry が closed rule で投影する。

初期ルール:

1. lifecycle が operational でなければ new execution unavailable。
2. required permission が不足なら unavailable。
3. plugin health unavailable → unavailable。
4. capability health unavailable → unavailable。
5. plugin/capability health degraded → degraded。
6. health unknown → unknown。
7. 上記を全て満たす → available。

Foundation `CapabilityAvailability`へ:

```text
HEALTHY + permission OK + operational → AVAILABLE
DEGRADED + permission OK + operational → DEGRADED
UNAVAILABLE / permission missing / stopping → UNAVAILABLE
UNKNOWN → UNKNOWN
```

Permission不足をDEGRADEDとして緩和しない。

---

## 11. Registry revisions and generation safety

### 11.1 registry_revision

Registryが外部へ公開するstateが変わるaccepted mutationごとに1以上進むmonotonic revision。

例:
- plugin discovered/validated/registered
- availability/health change
- permission grant revision adoptionによるeffective view change
- stop/unregister
- re-add

failed/no-op mutationでrevisionを進めない。

### 11.2 plugin_generation

同一 `plugin_id` のruntime registration generation。

- first registrationからstrict integer generationを持つ。
- unregister後に同じplugin_idを再addする場合はgenerationを進める。
- old generationのhealth/lifecycle reportを新generationへ適用しない。

### 11.3 capability revision

Foundation `CapabilityDescriptor.revision` は capability identity ごとのmonotonic generation。

revisionを進める条件:
- effective availability change
- operation set change
- operation schema ref change
- permission declaration/effective availability change
- side-effect/cancellation/timeout metadata change
- plugin version / generation change
- immutable attributes payload change

### 11.4 Tombstone revision floor

**capabilityをunregisterしても、そのcapability IDの最後のrevision floorをRegistryから消さない。**

再登録時:

```text
new_descriptor_revision > last_tombstoned_revision
```

を必須とする。

理由:
#329 `CapabilityBinding` は `capability_id + descriptor_revision` を実行provenanceへ固定する。同じIDをremove/re-addした際にrevisionを0等へリセットすると、old in-flight bindingとnew capability generationが誤一致する可能性がある。

TombstoneはCapability利用可能性を意味しない。identity/revision safety用metadataである。

---

## 12. Foundation CapabilityDescriptor projection

Registryは各effective capabilityからFoundation Descriptorを生成する。

```text
CapabilityDescriptor(
  capability_id,
  capability_type,
  permitted_operations,
  effective_availability,
  capability_revision,
  attributes
)
```

### 12.1 permitted_operations

Manifest operationのうち、required permissionが全てgrantされたoperationのみ。

元Capabilityが複数operationを持ち、一部operationだけpermission不足の場合:
- 許可済みoperationだけDescriptorへ公開可能。
- operation setが変わるためdescriptor revisionを進める。
- 0 operationsはFoundation Descriptorを作れないため、そのCapabilityはexecution discovery viewから除外し、Registry diagnostic viewではUNAVAILABLEとして保持する。

### 12.2 closed attributes schema

Registry projection attributes:

```text
schema_id: plugin.capability.attributes.v1
plugin_id
plugin_version
plugin_generation
contract_version
operations:
  - operation_id
    input_schema_ref
    output_schema_ref
    side_effect_class
    cancellation_support
    timeout_support
required_permissions
```

- credential / raw SDK / prompt / raw user textは禁止。
- consumerがattributes文字列からGoal/semantic meaningを推測しない。
- attrs payloadはimmutable strict JSON。

### 12.3 Descriptor consumer boundary

- Executive / Planner: available capability factsとしてread-only利用。
- #329: existing `CapabilityRequirement` matching / `CapabilityBinding`へ利用。
- GUI/Admin: typed Registry diagnostic viewを優先し、attributes free-form parsingをUI Authorityにしない。

---

## 13. Registry snapshots

### 13.1 PluginRegistrySnapshot

```text
PluginRegistrySnapshot
- registry_revision
- plugins[]: RegisteredPluginView
- capabilities[]: RegisteredCapabilityView
- foundation_capabilities[]: CapabilityDescriptor
- captured_at
```

### 13.2 RegisteredPluginView

```text
RegisteredPluginView
- plugin_id
- plugin_version
- contract_version
- plugin_generation
- lifecycle_state
- health_state
- manifest
- missing_permissions[]
```

### 13.3 RegisteredCapabilityView

```text
RegisteredCapabilityView
- capability_id
- plugin_id
- plugin_generation
- capability_revision
- declaration
- effective_availability
- permitted_operations[]
- missing_permissions[]
```

Snapshots are immutable and deterministically ordered by stable IDs.

Registry snapshot consumer may not mutate Registry state through returned objects.

---

## 14. Atomic registration

Registering one manifest with N capabilities is all-or-nothing.

Before state mutation validate:

1. manifest structural validity。
2. supported contract version。
3. plugin_id not active。
4. capability IDs unique inside manifest。
5. capability IDs do not collide with active Registry capability IDs。
6. operation IDs unique per capability。
7. schema refs / permission refs valid。
8. optional dependency declarations valid and non-self。
9. lifecycle hook declarations valid。

Any failure:
- no partial Plugin registration。
- no partial capability index。
- no registry revision increment。
- no lifecycle hook execution by Domain Registry。

Success:
- plugin generation assigned。
- capability revisions assigned above tombstone floors。
- Plugin enters REGISTERED atomically。
- initial Capability descriptors remain UNKNOWN/UNAVAILABLE until effective health/permission state permits use。

---

## 15. Permission refresh / health refresh

A permission grant revision or health observation may change multiple capabilities at once.

The Registry applies one validated refresh atomically:

```text
validate input
→ compute complete next Plugin/Capability view
→ compute changed descriptor revisions
→ one registry state swap
→ publish one new registry_revision
```

Consumers must not observe half-updated operation/permission availability from the same refresh.

Same input producing no effective state change is idempotent no-op and does not advance registry revision.

---

## 16. Stop / unregister / hot remove

### 16.1 New execution fence

stop request accepted:

```text
AVAILABLE/DEGRADED/UNAVAILABLE
→ STOPPING
```

At STOPPING commit:
- all Foundation descriptors for that Plugin become unavailable/removed from executable discovery in one atomic mutation。
- descriptor revisions advance。
- new #329 preflight must not bind them。

### 16.2 In-flight execution

Registryは既にstartした#329 executionを「存在しなかった」ことにしない。

- existing `CapabilityBinding` / `ExecutionResult`は#329 Authorityの履歴。
- stop coordinator may request cancellation according to #329 interruptibility/cancellation contract。
- already applied external effectはRegistry removeで消去しない。
- late reportは#329のstale/effect preservation rulesへ従う。

### 16.3 Stop I/O

Plugin provider の concrete stop call は Port / Adapter側。

Registry lock内でawaitしない。

```text
Registry STOPPING commit
→ outside-lock PluginLifecyclePort.stop(...)
→ typed PluginLifecycleReport
→ Registry STOPPED commit
→ UNREGISTERED commit
```

Provider stop failure:
- Core全体を停止しない。
- Plugin remains typed STOPPING / UNAVAILABLE or transitions to typed failure policy。
- retry/backoffはbounded external coordinator responsibility。

### 16.4 Re-add

UNREGISTERED後に同じplugin_idを再add可能。

- new plugin_generation。
- capability revisions continue above tombstones。
- old health/lifecycle report cannot affect new generation。

---

## 17. Lifecycle Port boundary

Optional application Port:

```text
PluginLifecyclePort
- start(request) -> PluginLifecycleReport
- stop(request) -> PluginLifecycleReport
- health(request) -> PluginHealthObservation
```

Request/reportはPlugin identity + generation + bounded contextのみ。

Domainへ入れない:
- Python module object
- process handle
- HTTP client
- SDK exception
- token/credential

Provider exceptionはAdapterでtyped failureへ正規化する。

RegistryがLifecyclePortを直接awaitしながらatomic lockを保持してはならない。

---

## 18. Concurrency and synchronization

### 18.1 Registry mutation

- short atomic critical section only。
- external I/O / lifecycle hook / provider callback / DB I/Oをlock内でawaitしない。
- snapshotsはimmutableなのでread側は長時間lockを保持しない。

### 18.2 Races

Required closed outcomes:

- duplicate concurrent register → at most one success。
- health update vs stop → STOPPING fence wins; health cannot resurrect availability。
- old health observation vs re-add → generation mismatch reject。
- permission refresh vs unregister → resulting state must be one atomic ordered revision, not partial merge。
- same expected registry revisionを持つconcurrent mutation → one wins, other typed stale/conflict。

### 18.3 Runtime isolation

Registry update / health polling / lifecycle I/Oで:
- Body realtimeをblockしない。
- current Speechをblockしない。
- Game frame loopをblockしない。
- unrelated Executive/Activityをglobal lockしない。

#343は#322 schedulerを再実装しない。

---

## 19. Registry mutation command / expected revision

Public mutation pathは必要に応じて `expected_registry_revision` を受け取る。

- callerがknown revisionからの変更を要求する場合、currentと不一致ならfail-closed stale/conflict。
- unconditional internal observation updateもplugin generation / observation revision gateを必須にする。
- stale callerがnew Registry stateを上書きしない。

Registry自身がsemantic conflict resolutionをLLMへ依頼しない。

---

## 20. Lifecycle facts and external notification

Registry accepted mutationからbounded typed lifecycle factを投影可能:

```text
PluginRegistryLifecycleFact
- fact_id
- registry_revision
- plugin_id
- plugin_generation
- lifecycle_state
- affected_capability_ids[]
- occurred_at
```

Capability availability changeもtyped fact/eventへ投影可能だが、consumerのGoal/Attention/Characterを直接mutationしない。

```text
Registry fact
→ typed Event Gateway
→ Appraisal / Attention / Executive as appropriate
```

Registryが「unavailableだから別行動をする」と決めない。

---

## 21. Failure codes

Typed failure candidates:

```text
MANIFEST_INVALID
CONTRACT_VERSION_UNSUPPORTED
PLUGIN_ALREADY_ACTIVE
CAPABILITY_ID_CONFLICT
DEPENDENCY_DECLARATION_INVALID
PERMISSION_SNAPSHOT_INVALID
HEALTH_OBSERVATION_STALE
GENERATION_STALE
REGISTRY_REVISION_STALE
LIFECYCLE_TRANSITION_INVALID
LIFECYCLE_PROVIDER_FAILED
```

Failure payloadへ:
- credential
- SDK exception text
- raw manifest secret
- raw user text

をコピーしない。

---

## 22. Security / trust boundary

- Manifestはデータであり、Registry validation時に任意codeとして実行しない。
- discovery adapterがfile/package/serviceから読み出す方式はDomain非責務。
- manifest fieldをimport path / shell / URL実行命令として扱わない。
- Pluginが自分でpermission grantを生成しない。
- Provider/Adapterだからという理由だけでPlugin登録しない。
- Plugin event / health / lifecycle reportからCore Authorityを作らない。
- Registry diagnosticsへsecretを露出しない。

---

## 23. Relationship to #329 Activity Execution

#343と#329の責務は次のように固定する。

```text
#343 Registry
  manifest / lifecycle / health / permission
  → Foundation CapabilityDescriptor snapshot

#329 Activity Execution
  SystemCommand.required_capabilities
  + current CapabilityDescriptor snapshot
  → CapabilityBinding(capability_id, descriptor_revision)
  → preflight / dispatch / Actual Execution Fact
```

#343は:
- `ExecutionResult`を作らない。
- Activity commandをadmitしない。
- external effect refsを作らない。
- #329 recordを削除しない。

#329は:
- Plugin Manifestを解釈しない。
- Plugin lifecycle state machineを所有しない。
- permission grant sourceを所有しない。

Permission/healthによる effective availability change は Foundation descriptor revision を進めるため、#329のsecond preflightが既存の `capability_changed` gateで検出できる。

---

## 24. Relationship to Executive / Planner

Executive / Plannerへ渡すのはread-only current Capability facts。

- Pluginの存在を「使うべき」というGoalへ昇格しない。
- Plugin display nameやoperation nameをraw natural-language triggerへしない。
- Capability type / operationはtyped requirement matchingにだけ使う。
- unavailable/degradedをExecutiveが考慮できるが、Registryは代替Goalを選ばない。

---

## 25. Required tests

### Manifest / schema

- valid manifest
- unknown/invalid field typed rejection at parser boundary if parser exists
- unsupported contract version
- duplicate capability ID within manifest
- duplicate operation ID within capability
- self optional dependency reject
- invalid permission ref
- invalid resource requirement
- mutable caller collections cannot mutate manifest after construction

### Registration

- first registration success
- same plugin active duplicate reject
- cross-plugin capability_id collision reject
- multi-capability registration all-or-nothing
- failed registration does not advance registry revision
- overlapping capability_type/operation with unique capability IDs is permitted

### Permission

- all exact grants → operation available
- missing one permission → operation not published
- scope mismatch → not granted
- no prefix/substring/glob implicit match
- capability with zero permitted operations is unavailable / not executable
- permission refresh changes descriptor revision
- Plugin health cannot override missing permission

### Health

- healthy / degraded / unavailable / unknown projection
- capability-level override
- unknown capability health reject
- observation revision rollback reject
- same observation revision different payload reject
- old generation observation reject
- health update during STOPPING cannot restore availability

### Lifecycle

- DISCOVERED→VALIDATED→REGISTERED→operational
- illegal direct transition reject
- stop fence removes new execution availability before provider stop await
- STOPPED→UNREGISTERED
- re-add uses new plugin generation
- provider stop failure does not crash Core / erase Registry history

### Revision safety

- registry revision monotonic
- no-op update does not advance revision
- descriptor revision advances on availability / operation / metadata change
- unregister retains capability tombstone revision floor
- re-add same capability ID receives revision greater than old tombstone
- stale expected registry revision mutation reject

### Foundation projection

- deterministic stable ordering
- exact Foundation CapabilityDescriptor fields
- closed attributes schema only
- credential/provider object/raw text absent
- #329 `CapabilityRequirement` can satisfy available descriptor
- degraded satisfies only allow_degraded requirement
- unavailable/unknown does not satisfy
- permission/health change detected by #329 descriptor revision gate

### Concurrency

- concurrent duplicate register at most one success
- health vs stop race cannot resurrect stopped capability
- re-add vs old report generation fence
- permission refresh vs unregister atomic ordering
- slow lifecycle Port call while unrelated async task continues
- Registry lock never spans awaited provider operation

### Authority regression

- Registry cannot mutate Goal/Internal State/Character/Body
- Registry does not interpret raw user text
- Plugin manifest cannot create ExecutionResult
- lifecycle report cannot assert Actual external effect
- removing Plugin does not erase #329 already-recorded effects
- Provider / Infrastructure Adapter is not auto-classified as Plugin

---

## 26. Non-goals

- Plugin 0件Core Integration (#344)
- actual Capability execution (#329)
- provider-specific Plugin implementation
- dynamic Python import system
- marketplace / remote package install
- signature distribution / package supply-chain system
- per-user authorization UI
- Plugin settings GUI
- Game Skill realtime runtime
- Streaming Subsystem implementation
- Registry persistence across restart

Persistenceが必要になった場合も、rehydrationはtrusted validation boundaryを別途設計し、arbitrary stored lifecycle stateを直接Authorityへ戻さない。

---

## 27. Design Gate acceptance

#343 implementation開始前に次を満たす。

- 本文書を#343 canonical supplementとしてIssueへ記録する。
- active V2 lineageを `feature/v2-plugin-registry` 1本へ固定する。
- baseはcurrent `rebuild/v2-foundation`と一致する。
- #321 / #329 completed。
- Project #7 #343 = `In progress`。
- Foundation `CapabilityDescriptor`を再定義せずprojectionとして利用する。
- permission grant sourceとPlugin declarationを分離し、self-escalationを禁止する。
- availabilityをlifecycle + permission + healthからclosed ruleで導出する。
- capability descriptor revisionのremove/re-add resetを禁止しtombstone floorを持つ。
- stop fenceとin-flight #329 Fact保持を分離する。
- Registry I/O awaitとatomic mutation lockを分離する。
- required testsを本文へ固定する。
- exact-head deterministic CI PASS。
- ChatGPT Design Reviewでblocking finding 0。

以後 Design → Code を維持する。
