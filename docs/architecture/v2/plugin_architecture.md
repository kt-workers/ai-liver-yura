# AI Liver ゆら V2 Plugin Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Parent Issue: #342
Root management: #317

## 1. 目的

Pluginを「なくても動く機能」というruntime optionalityだけで定義しない。

Bodyのように一時的なdegraded運転が可能でもCore固有責務であるものが存在するため、Core ownershipとoptional availabilityは別軸で扱う。

Pluginは次のように定義する。

> **Pluginは、BrainやBodyなどCore自身の構成要素ではなく、Coreが公開する拡張契約を通して外部から新しいCapabilityを追加する機構である。**

Pluginの追加・削除で、Coreが所有するDomain StateやAuthority境界を変えてはならない。

---

## 2. Plugin判定基準

ある機能をPluginと呼ぶには原則として次を満たす。

1. Core固有Domain Stateの正本を所有しない。
2. CoreのExecutive / State / Body等のAuthorityを所有しない。
3. Coreの公開Plugin / Capability Contractを通して接続する。
4. Brain / Bodyの内部実装変更なしに追加・削除できる。
5. ゆら自身の基本構造ではなく、外部から新しい能力を追加する。
6. unavailable / failureをtyped capability stateとして表せる。

「なくてもSystemが何らかの形で動ける」は補助的性質であり、Plugin定義そのものではない。

---

## 3. Core / Plugin / Provider / Subsystemの違い

### Core

ゆら自身の恒常的責務。

例:
- Brain
- Body
- Internal State
- Executive Authority

### Plugin

CoreへCapabilityを追加する拡張機構。

例候補:
- Web search capability
- local tool capability
- game-control capability adapter
- filesystem/tool capability等

### Infrastructure Provider / Adapter

Core Portの実装手段。

例:
- OpenAI Provider
- local LLM Provider
- VOICEVOX
- PostgreSQL
- HTTP transport

外部実装だからPluginなのではない。

### Subsystem

Coreとは別の独立システム境界を持つもの。

例:
- Streaming
- Avatar presentation
- GUI/Admin
- Validation Labs

Subsystem内部でAIやPlugin adapterを利用してもよい。

---

## 4. PluginはExecutiveを迂回しない

```text
ExecutiveDecision
→ capability request / ActivityPlan
→ Plugin Capability Contract
→ Plugin execution
→ typed CapabilityExecutionResult
→ Core Event / Appraisal
```

禁止:

```text
raw user text
→ Plugin独自意味解釈
→ 勝手にActivity開始
```

```text
Plugin
→ Characterへ直接台詞命令
```

```text
Plugin
→ Bodyへ直接motion command
```

Pluginが返すのは能力実行結果や外界Eventであり、ゆらの意思決定Authorityではない。

---

## 5. Capability Contract

最低限:

```text
CapabilityDescriptor
- capability_id
- provider/plugin_id
- version
- operations[]
- input_schema_ref
- output_schema_ref
- permissions
- availability
- health
- latency_class?
- concurrency_policy?
- cancellation_support
```

```text
CapabilityRequest
- request_id
- capability_id
- operation
- source_decision_id / activity_plan_id
- source_context_revision
- payload
- priority
- timeout_policy
- cancellation_token_ref
- preconditions[]
```

```text
CapabilityExecutionResult
- request_id
- capability_id
- lifecycle_state
- output?
- failure?
- started_at?
- observable_at?
- completed_at?
- external_effect_refs[]
```

Plugin固有SDK objectをCore Domainへ渡さない。

---

## 6. Capability lifecycle

```text
registered
→ available
→ degraded / unavailable
→ available
→ unregistering
→ unregistered
```

Execution lifecycle:

```text
requested
→ accepted
→ started
→ observable/applied
→ completed

or
rejected / unsupported / failed / cancelled / timed_out
```

「request accepted」と「外部効果が実際に発生した」を区別する。

---

## 7. Plugin Registry

Issue: #343

RegistryはCapability discoveryとlifecycleを所有する。

```text
PluginRegistry
- registered plugins
- capability index
- operation schema refs
- health / availability
- lifecycle state
- version compatibility
```

Registryは意味判断をしない。

Executive / PlannerはCapabilitySnapshotをread-onlyで受け取る。

---

## 8. Manifest

Plugin manifestは宣言的情報を持つ。

例:

```text
PluginManifest
- plugin_id
- name
- version
- contract_version
- capabilities[]
- required_permissions[]
- optional_dependencies[]
- resource requirements
- lifecycle hooks
```

ManifestへCharacter personalityやCore state schemaを書き込まない。

---

## 9. Permissions / Authority

Capabilityごとに明示permissionを持てる。

例:
- read-only
- external side effect
- filesystem write
- network access
- game controller output
- account operation

ExecutiveがCapabilityを選んでも、permission / safety / capability preflightを通す。

Plugin自身がpermissionを自己昇格しない。

---

## 10. Concurrency

Plugin executionをCoreのblocking chainにしない。

```text
slow plugin request
while
  input reception continues
  Body realtime continues
  current speech continues
  unrelated Executive work may continue
```

requestは:

- priority
- timeout
- cancellation
- source_context_revision
- preconditions

を持つ。

結果到着時にstaleでも、外部効果が既に起きている可能性は区別する。

```text
request became stale
+ external effect not started
→ cancel safely

request became stale
+ external effect already applied
→ result factを記録
→ Appraisal / Executiveへfeedback
```

staleだから実世界の事実を無かったことにはしない。

---

## 11. Gameとの境界

ゲーム機能は1種類の実装へ固定しない。

### 11.1 Coreから見たGame capability

Core Executive / Activity Plannerからは高レベルCapabilityとして見える。

例:

```text
start_game_session
join_match
set_high_level_strategy
request_pause
end_session
```

### 11.2 Game-specific realtime agent

frame-level actionはCore Executive LLMへ毎frame問い合わせない。

```text
Executive Goal / Strategy
→ Game capability
→ game-specific agent
   - deterministic logic
   - search/planner
   - RL
   - LLM/VLM where appropriate
→ controller actions
→ typed game events/results
→ Core Appraisal
```

Game-specific agentは技能実行者であり、Core Executive Goal Authorityを奪わない。

### 11.3 PluginかSubsystemか

軽量なgame integrationはPluginとしてCapabilityを提供できる。

独立process、リアルタイム制御、複雑な状態管理、専用AI runtime等を持つ場合はSubsystem / Skill serviceとして分離し、Core側のPlugin/Capability adapterが公開契約を橋渡ししてよい。

分類は「optionalだから」ではなく責務・ownership・process boundaryで決める。

---

## 12. Search / Tool AI

検索やTool利用に専用LLM/AIを使ってよい。

それらはSkill AIであり、Core cognitive LLM Role数には含めない場合がある。

ただし:
- raw user textを勝手に再解釈してExecutiveを迂回しない
- Tool結果をExecution Fact / Evidenceとしてtypedに返す
- external side effectはpermissionとlifecycleを持つ

---

## 13. Plugin Event input

Pluginは外界Event sourceにもなり得る。

例:
- game match ended
- search completed
- tool disconnected
- external sensor signal

```text
Plugin external event
→ typed PluginEvent
→ Input/Event Gateway
→ Appraisal / Executive as appropriate
```

PluginがInternal Stateを直接変更しない。

---

## 14. Failure / Degradation

Plugin unavailableはCore failureではない。

```text
Capability unavailable
→ CapabilitySnapshot更新
→ affected plan/request rejected/degraded
→ Executive may reconsider
```

retryはbounded。

高頻度failure logを無制限に出さない。

shutdown中は新規executionを停止し、interruptible requestをcancelし、resource closeを行う。

---

## 15. Hot add / remove

可能なPluginではruntime add/removeを支援できる。

条件:
- registry revision更新
- in-flight request policy
- dependency validation
- new CapabilitySnapshot発行
- Executive再評価trigger可能

Plugin removeでCore Domain schemaを破壊する設計は禁止。

---

## 16. Zero-plugin invariant

Plugin定義とは別のSystem invariantとして:

> Pluginが1つも登録されていない構成でも、Brain / Bodyを含むCoreは自身の基本責務を維持できる。

これは「Coreが外部Providerなしに全機能を実行できる」という意味ではない。

例えばLLM ProviderやTTS unavailableでは個別能力がdegradedになるが、それらInfrastructure ProviderをPluginへ再分類しない。

---

## 17. V1から継承する教訓

- PluginとSubsystemを混同しない
- Core Runtimeへ個別game/tool実装を埋め込まない
- Capability / Activity / Execution Resultをtypedにする
- optional failureでCoreを破壊しない
- external operationを実行済みと早期主張しない

改善:
- optionalityをPlugin定義そのものにしない
- BodyをPlugin化しない
- Provider/AdapterをPluginと呼ばない
- Plugin AIをCore Executive Authorityと混同しない
- slow external capabilityでCore laneをblockしない

---

## 18. Acceptance

### #343 Registry / Lifecycle

- manifest validation
- register / unregister
- duplicate capability reject
- version compatibility
- availability / health change
- permission metadata
- registry revision

### #344 Integration

- zero-plugin Core configuration
- one capability register / execute / result
- capability unavailable
- cancellation
- stale request before effect
- stale result after external effect
- slow Plugin中もunrelated Core lane継続
- Plugin cannot directly mutate Internal State
- Plugin cannot directly command Character/Body
- add/remove without Brain/Body schema change

### Game boundary

- high-level strategy from Core
- frame-level agent independent from Executive latency
- game result returns typed Event/Fact
- Game Agent cannot change Core Goal Authority

---

## 19. Design Gate

- [ ] #342が本書をcanonicalとして参照
- [ ] #343/#344が本書と一致
- [ ] optionality-only Plugin定義がV2から消える
- [ ] BodyはCoreとして維持
- [ ] Infrastructure ProviderとPluginを分離
- [ ] Subsystem / Plugin / Skill AI境界を明示
- [ ] zero-plugin invariantをPlugin定義と分離
- [ ] Plugin execution concurrency / cancellation / stale effect semanticsを定義
