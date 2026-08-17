# V2 Plugin Registry 実装整合ノート

Owner Issue: #343
Active implementation: `feature/v2-plugin-registry` / PR #424
Status: Implementation Alignment Note

## 1. Authority

本書は次のcanonicalを置換・再定義しない。

- `docs/architecture/v2/plugin_architecture.md`
- `docs/architecture/v2/plugin_registry_contracts.md`
- `docs/architecture/v2/plugin_registry_permission_principal_contracts.md`
- upstream `foundation_contracts.md`
- upstream `activity_execution_contracts.md`

2026-08-17のcurrent-head reviewで確認された実装不足について、既存canonicalを実装APIへどう写像するかだけを固定する。

## 2. Registry revision commit rule

`registry_revision` は、1回のaccepted mutationで外部公開される `PluginRegistrySnapshot` の
`plugins` または `capabilities` が変化した場合に **exactly one generation** 進める。

同じmutationで複数Capabilityのdescriptor revisionが進んでも、Registry revisionは1回だけ進める。

以下を含む。

- `DISCOVERED → VALIDATED`
- `VALIDATED → REGISTERED`
- operational state → `STOPPING`
- `STOPPING → STOPPED`
- `STOPPED → UNREGISTERED`
- permission refreshによるeffective view変更
- health observationによるeffective view変更
- unregister後のre-add

failed mutationと、外部公開stateが変わらないidempotent/no-op mutationでは進めない。

grant revisionまたはhealth observation revisionだけが新しくても、外部公開Plugin/Capability viewが同じなら
Registry revisionは進めない。

## 3. Expected Registry Revision

callerが既知のRegistry snapshotを根拠にmutationするpublic pathは、keyword-only
`expected_registry_revision: int | None` を受け取れる。

対象:

- `discover`
- `validate`
- `register`
- `register_manifest`
- `adopt_permission_grants`
- `begin_stop`
- `mark_stopped`
- `unregister`

指定された値はatomic lock内でcurrent `registry_revision`とexact比較する。
不一致は `REGISTRY_REVISION_STALE` としてfail-closedにし、stateを変更しない。

同じexpected revisionから競合する2 mutationが同時に来た場合、最初のvisible mutationだけがcommitでき、
後続mutationはstale/conflictになる。

`apply_health_observation` はcaller-originated expected revisionを要求しない。
既存canonicalどおり `plugin_generation` / `observation_revision` / `observed_at` のtyped gateで守る。

## 4. Permission identity

Permission identityは全宣言levelで常に次のexact pairとする。

```text
(permission_id, scope_ref)
```

- Manifest
- Capability
- Operation

同じ `permission_id` でも `scope_ref` が異なれば別Permissionとして共存できる。
同一pairだけをduplicateとしてrejectする。

Grantはさらにprincipalを含む次のexact identityで一意とする。

```text
(plugin_id, permission_id, scope_ref)
```

prefix / substring / regex / globによる暗黙一致は行わない。

## 5. Regression matrix

#343修正後は最低限次をcurrent-headで固定する。

- lifecycle-only accepted mutationでもRegistry revisionが進む
- visible mutation 1回につきRegistry revisionは1回だけ進む
- no-op grant / no-op healthはRegistry revisionを進めない
- stale `expected_registry_revision` はstate非変更でreject
- same expected revision concurrent mutationは高々1件success
- same permission ID + different scopeはManifest/Capability/Operationで共存
- exact duplicate permission pairはreject
- permission revocationでoperation set / descriptor revisionが更新
- STOPPING fenceとold-generation health gate
- unregister/re-addのdescriptor tombstone floor
- Foundation `CapabilityDescriptor` projectionと`CapabilityRequirement`
- #329 old bindingはdescriptor revision変更後のsecond preflightでreject
- Plugin remove後も#329 `ExecutionResult` / effect historyは保持
- concurrent duplicate register / health-stop / permission-unregister
- external lifecycle await中にRegistry lockを保持しない
- RegistryがGoal / Internal State / Character / Body / Execution Fact Authorityを取得しない
