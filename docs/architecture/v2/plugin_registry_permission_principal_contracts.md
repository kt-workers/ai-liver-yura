# V2 Plugin Registry Permission Principal Contracts

Owner Issue: #343
Parent canonical: `docs/architecture/v2/plugin_registry_contracts.md`
Status: Canonical Security Supplement / Design Gate

## 1. Purpose

`plugin_registry_contracts.md` §6 のpermission grantについて、**grantの対象principalをPlugin identityへ明示的に固定**する。

permission IDとscopeだけのglobal grant集合では、同じpermissionを要求する別Pluginまで誤って許可済みになる可能性がある。

例:

```text
Plugin A requires network_access
Plugin B requires network_access
Host intended to grant only A
```

`grants[]: PluginPermissionRef`だけではA/Bを区別できない。

したがって、#343のpermission grant Authorityは本補足を優先する。

---

## 2. Principal-bound grant

### 2.1 PluginPermissionGrant

```text
PluginPermissionGrant
- plugin_id
- permission: PluginPermissionRef
```

- `plugin_id`はgrant principalであり、exact matchのみ許可する。
- `permission`も`permission_id + scope_ref`のexact identityで照合する。
- prefix / substring / regex / glob / display name / provider classによるprincipal照合は禁止。
- capability_idやoperation名からplugin_idを推測しない。

### 2.2 PluginPermissionGrantSnapshot

```text
PluginPermissionGrantSnapshot
- grant_revision
- grants[]: PluginPermissionGrant
- captured_at
```

`grants[]: PluginPermissionRef`だけを持つ旧記述は本補足で置換する。

Registryはgrant sourceを所有しない。Trusted host / composition / deployment configuration等がsnapshotを生成する。

---

## 3. Effective permission evaluation

Plugin `P` のoperation `O`に必要なpermission集合:

```text
manifest.required_permissions
∪ capability.required_permissions
∪ operation.required_permissions
```

各required permission `R`について、次を両方満たすgrantが存在する場合だけgrantedとする。

```text
grant.plugin_id == P.plugin_id
grant.permission == R
```

他Plugin向けgrantは存在しても無関係である。

```text
Grant(plugin-a, network_access)
!=
Grant(plugin-b, network_access)
```

### 3.1 Cross-plugin isolation

Plugin AへのgrantをPlugin Bが利用してはならない。

- same permission IDでも不可。
- same scopeでも不可。
- same capability type / operationでも不可。
- same provider implementationでも不可。

### 3.2 Stable plugin identity and re-add

Grant principalはstable logical `plugin_id`へbindする。

runtime `plugin_generation`へはbindしない。process restart / unregister→re-addだけでHuman/host permission設定を自動失効させる責務は#343 v1に持ち込まない。

ただし:
- re-addしたManifestが新しいpermissionを要求した場合、そのpermissionは既存grantに存在しない限りunavailableとなる。
- Pluginはmanifest変更でgrantを自動追加できない。
- same plugin_idを別実装が不正に奪うpackage supply-chain問題は#343 v1のnon-goalであり、将来signature/install trust設計で扱う。

---

## 4. Grant snapshot validation

最低限:

- `grant_revision`はstrict non-negative int。bool不可。
- `captured_at`はtimezone-aware。
- `(plugin_id, permission_id, scope_ref)`はsnapshot内で一意。
- empty plugin_id / permission_id / scope_refは禁止。
- mutable caller collectionをimmutable tupleへowned copyする。
- Plugin自身がhealth/lifecycle/manifest report内へgrantを埋め込んでもAuthorityとして採用しない。

Grant snapshotの採用はRegistry mutationであり、effective capability viewが変化した場合のみRegistry / affected capability descriptor revisionを進める。

同じgrant snapshotによるeffective state no-opではrevisionを進めない。

---

## 5. Permission revocation

Trusted snapshotからPlugin向けgrantが消えた場合:

1. Registryはcomplete next permission stateを計算する。
2. 対象operationをpermitted operationsから除外する。
3. descriptor operation set / availabilityが変わる場合はcapability revisionを進める。
4. capabilityにpermitted operationが0件ならexecutable Foundation descriptorを公開しない。
5. Registry diagnostic viewはmissing permissionを保持する。

revocationは**新規#329 preflight**を閉じる。

既にstartした#329 executionや既発生effectをpermission revocationだけで消去・書換えしない。in-flight cancellation policyは#329 / Runtime lifecycle側の別Authorityで扱う。

---

## 6. Security invariants

- Plugin declaration != Plugin grant。
- Plugin A grant != Plugin B grant。
- health state != permission grant。
- capability availability report != permission grant。
- display name / package name / module name != permission principal。
- raw user textでgrantを作らない。
- Manifestの`required_permissions`をgrant済みと自己解釈しない。
- Plugin lifecycle Providerへgrant mutation権限を渡さない。

---

## 7. Required tests

### Principal binding

- Plugin A `network_access` grant → Aのみgranted。
- same permissionを要求するPlugin Bはunavailableのまま。
- same scopeでもcross-plugin grant不可。
- same capability type/operationでもcross-plugin grant不可。

### Exact permission identity

- permission ID exact match。
- scope exact match。
- unscoped grantとscoped requirementは一致しない。
- scoped grantとunscoped requirementは一致しない。
- prefix / substring / glob風文字列を暗黙matchしない。

### Snapshot integrity

- duplicate `(plugin_id, permission, scope)` reject。
- invalid revision / bool revision reject。
- mutable collection aliasを保持しない。
- no-op grant refreshはregistry revisionを進めない。

### Revocation

- grant removalでoperationがFoundation descriptorから消える。
- descriptor revisionが進む。
- zero permitted operationsはnew execution discoveryから消える。
- #329 old started execution/effect historyを消さない。

### Re-add

- same stable plugin_id re-addは既存同permission grantを利用可能。
- newly requested permissionは明示grantなしでは利用不可。
- old plugin generationのhealth/lifecycle reportはpermission grantとは無関係にgeneration gateで拒否する。

---

## 8. Design precedence

`plugin_registry_contracts.md`と本書がpermission grant shapeについて異なる場合、**本書のprincipal-bound `PluginPermissionGrant`が優先**する。

実装時には両文書を同じ#343 canonical setとして扱う。
