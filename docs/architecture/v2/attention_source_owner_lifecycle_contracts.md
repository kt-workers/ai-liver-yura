# Attention Source Owner Lifecycle 型付き契約

Status: **Canonical Amendment / Issue #333 / adjacent #366 #329**

Applies to:
- `docs/architecture/v2/attention_turn_contracts.md`
- `docs/architecture/v2/attention_turn_contracts_amendment_2026-08-16.md`
- `docs/architecture/v2/goal_commitment_architecture.md` (#366)
- `docs/architecture/v2/activity_execution_contracts.md` (#329)

## 1. 目的と正本順位

本書は、Issue #333 の実装中に判明した owner-side lifecycle contract 不足を解消するための詳細正本である。

次の曖昧さを supersede する。

1. Goal / Commitment の current snapshot / `AutonomyTrigger` だけでは、Attention source を `offer / refresh / resolve` のどれとして扱うか一意に決められない。
2. Goal / Commitment の stable source に対する current / expected source revision が明示されていない。
3. Activity `ExecutionResult` は正しいstatus lifecycleを持つが、同一`command_id`のcurrent record世代をCASするowner-local revisionを持たない。
4. Application projectorがAttention Storeを読んで「初回か更新か」を推測することは、stateless projector / Authority境界に反する。

本書は上記4点について既存文書の曖昧な箇所を優先して解釈する。Goal / Commitment Authority、Activity Execution Authority、Attention Authority、Foundation `ExecutionResult` status machineそのものは変更しない。

---

## 2. 原則: lifecycle operationはownerが確定する

Attentionはsource ownerのlifecycleを推測しない。

```text
Owner atomic commit
  → typed owner lifecycle fact
  → #333 Application/Usecase projector
  → AttentionIngressSignal
  → Attention Store
```

禁止:

```text
owner snapshot
  → Attention Storeをpoll
  → sourceがある/ないからOFFER/REFRESHを推測
```

禁止:

```text
current snapshot同士をApplication側でdiff
  → terminal removalを後付け推測
```

`OPEN / REFRESH / CLOSE` はownerのatomic transitionがbefore/after stateを知っている時点で確定する。

---

## 3. Owner-neutral lifecycle operation

ownerはAttention Domainのenumをimportしない。共有Foundation contractとして次のclosed enumを用いる。

```text
SourceLifecycleOperation
- OPEN
- REFRESH
- CLOSE
```

意味:

- `OPEN`: stable source identityの新規lifecycle開始。
- `REFRESH`: 同じstable source identityのcurrent state更新。
- `CLOSE`: 同じstable source identityのlifecycle終了。

#333 Application projectorだけが次へ変換する。

```text
OPEN    → AttentionIngressOperation.OFFER
REFRESH → AttentionIngressOperation.REFRESH
CLOSE   → AttentionIngressOperation.RESOLVE
```

owner側で`offer / refresh / resolve`というAttention固有語を持つ必要はない。

---

## 4. Version contract

versioned stable source lifecycle factは最低限次を持つ。

```text
- fact_id
- source_ref
- operation: SourceLifecycleOperation
- source_revision
- expected_source_revision?
- occurred_at
```

### 4.1 OPEN

```text
operation = OPEN
expected_source_revision = None
```

`source_revision`はownerがcommitした初期current stateのrevision。

### 4.2 REFRESH

```text
operation = REFRESH
source_revision = after revision
expected_source_revision = before revision
```

commit条件:

```text
Attention current source revision == expected_source_revision
and source_revision > expected_source_revision
```

revisionは必ずしも`+1`である必要はない。ownerのrevision体系がglobal store revisionを使い、別entity更新を挟んで飛ぶことを許す。

### 4.3 CLOSE

```text
operation = CLOSE
source_revision = terminal after revision
expected_source_revision = before revision
```

Attention側のCAS条件はREFRESHと同じ。

CLOSEの`source_revision`はterminal factのprovenanceであり、AttentionSourceとして保存し直すためのrevisionではない。CAS成功後にsourceを削除する。

### 4.4 fail-closed

REFRESH / CLOSEで次はrejectする。

- expected revisionがcurrent source revisionと一致しない
- source revisionがexpected以下
- source identity / kindが一致しない
- source context revisionがglobal currentより古い

reject時はAttention stateを完全に不変とする。

---

## 5. Global source context revisionとの分離

`source_revision`と`source_context_revision`は別Authorityである。

- `source_revision`: stable source ownerのentity / record lifecycle世代。
- `source_context_revision`: system側current context freshness。

Goal entity revisionやActivity record revisionを`source_context_revision`へ代用してはならない。

owner lifecycle factはowner-local lifecycleを確定する。#333 Application境界は、factをAttentionへprojectする時点で既存のauthoritative source-context contractから`source_context_revision`を取得・搬送する。

そのcontext値を使って`OPEN / REFRESH / CLOSE`を推測してはならない。

---

## 6. Goal owner contract — #366

既存`GoalState.revision`をstable source revisionとして使う。新しいAttention専用revisionは作らない。

新しいowner output fact:

```text
GoalLifecycleProjectionFact
- fact_id
- goal_id
- operation: SourceLifecycleOperation
- source_revision
- expected_source_revision?
- status: GoalStatus
- priority
- goal_store_revision
- occurred_at
```

identity:

```text
source_ref = goal_id
source_revision = after GoalState.revision
```

`goal_store_revision`はcommit後の`GoalCommitmentSnapshot.revision`であり、trace / snapshot provenance用。Attention source CASには`GoalState.revision`を使う。

### 6.1 operation mapping

#### 新規Goal作成

nonterminal `GoalState`が初めてcommitされた時:

```text
OPEN
after.revision = source_revision
expected = None
```

#### 既存Goal更新

reprioritize / activate / suspend / resume等、同じ`goal_id`がnonterminalのまま更新された時:

```text
REFRESH
source_revision = after.revision
expected_source_revision = before.revision
```

#### terminal Goal

completed / abandoned / failed / supersededへ合法遷移した時:

```text
CLOSE
source_revision = terminal after.revision
expected_source_revision = before.revision
```

terminalへの遷移がcommitされた後にfactを発行する。失敗したtransition、rollback、duplicate/idempotent no-opからfactを発行しない。

### 6.2 `AutonomyTrigger`との関係

既存`AutonomyTrigger`はcurrent Goal/Commitmentから作るbounded trigger viewとして残してよいが、**Attention source lifecycleの正本入力にはしない**。

理由:

- `AutonomyTrigger.goal_revision`はGoal Store snapshot revisionであり、個別Goal sourceのCAS世代ではない。
- snapshotから現在存在するtriggerだけを再生成しても、terminalで消えたsourceのCLOSEを一意に復元できない。
- snapshot diffを#333側で持つとowner Authorityを逆流させる。

#333のstable Goal source ingressは`GoalLifecycleProjectionFact`を使う。

---

## 7. Commitment owner contract — #366

既存`CommitmentState.revision`をstable source revisionとして使う。

```text
CommitmentLifecycleProjectionFact
- fact_id
- commitment_id
- operation: SourceLifecycleOperation
- source_revision
- expected_source_revision?
- status: CommitmentStatus
- priority
- goal_store_revision
- occurred_at
```

identity:

```text
source_ref = commitment_id
source_revision = after CommitmentState.revision
```

### 7.1 operation mapping

- 新規nonterminal Commitment commit → `OPEN`
- active / suspended等、同一Commitmentのnonterminal更新 → `REFRESH`
- released / fulfilled / violatedへterminal遷移 → `CLOSE`

REFRESH / CLOSEでは必ずbefore state revisionを`expected_source_revision`へ入れる。

Goalと同様、failed transition / rollback / duplicate no-opからfactを発行しない。

---

## 8. Activity Execution owner contract — #329

### 8.1 Foundation status machineは変更しない

Foundation `ExecutionResult`は引き続きActual Execution Fact status lifecycleの唯一の正本である。

新しいstatus enumや第二のActivity lifecycle machineを作らない。

ただし同じ`command_id`のcurrent `ActivityExecutionRecord`へCAS可能なowner-local versionが必要なため、recordに一般用途のrevisionを追加する。

```text
ActivityExecutionRecord
- ... existing fields
- record_revision
```

`record_revision`はAttention専用ではない。Activity ownerのcurrent record versionであり、read model、Event projection、CAS、debuggingにも使える。

### 8.2 record_revision

- record新規commit時に初期revisionを設定する。
- current recordが合法にmutationされた時だけmonotonicに進める。
- invalid transition / rejected mutation / duplicate no-op / rollbackでは進めない。
- `ExecutionResult.revisions` (`RevisionVector`) はsource-context等の実行前提であり、`record_revision`の代用にしない。
- 同じExecutionStatusで新effect_refを追加する合法milestoneもrecord mutationなのでrevisionを進める。
- cancellation requestの記録等、`ActivityExecutionRecord`自体がcurrent owner factとして変化する場合もrevisionを進める。

実装ではper-command local `+1`を推奨するが、#333側は「strictly newer」で検証し、`+1`そのものをcross-module invariantにはしない。

### 8.3 Activity owner lifecycle fact

```text
ActivityExecutionLifecycleFact
- fact_id
- command_id
- operation: SourceLifecycleOperation
- source_revision
- expected_source_revision?
- status: ExecutionStatus
- occurred_at
- effect_refs[]
```

identity:

```text
source_ref = command_id
source_revision = after ActivityExecutionRecord.record_revision
```

### 8.4 operation mapping

Activity sourceはraw Intent / Planではなく、#329 ownerがcommitした`ExecutionResult` record lifecycleを投影する。

#### REQUESTED record新規commit

```text
OPEN
status = REQUESTED
expected = None
```

`REQUESTED`は「実行済み」を意味しない。#329が確定したexecution lifecycle factであり、Attentionはその意味を再解釈しない。

#### nonterminal record更新

ACCEPTED / PLANNED / STARTED / OBSERVABLE / APPLIED、および同一statusへの合法effect追加等:

```text
REFRESH
source_revision = after.record_revision
expected_source_revision = before.record_revision
```

#### terminal record更新

COMPLETED / REJECTED / UNSUPPORTED / FAILED / CANCELLED / TIMED_OUT / SUPERSEDED:

```text
CLOSE
source_revision = terminal after.record_revision
expected_source_revision = before.record_revision
```

これにより、pre-start reject/unsupportedも「OPENされていないterminal one-shot」という特殊ケースにならない。REQUESTED commitでstable source lifecycleは必ず開始済みである。

### 8.5 Actual Fact semantics

AttentionがREQUESTED / ACCEPTED lifecycle factを受けても、「外部effectが起きた」「完了した」と解釈してはならない。

- execution truth Authority = `ExecutionResult.status / effect_refs`
- Attention Authority = scheduling eligibility

したがってActivity Attention projectorはraw `ActivityInvocation` / `SystemCommand` / `ActivityPlan`を受理せず、owner-committed `ActivityExecutionLifecycleFact`だけを受理する。

---

## 9. Projector contract — #333 Application/Usecase

各projectorはstatelessである。

```text
GoalLifecycleProjectionFact
  → GoalAttentionProjector
  → AttentionIngressSignal

CommitmentLifecycleProjectionFact
  → CommitmentAttentionProjector
  → AttentionIngressSignal

ActivityExecutionLifecycleFact
  → ActivityAttentionProjector
  → AttentionIngressSignal
```

mapping:

```text
owner.operation OPEN
  → ingress OFFER
  → source_revision = fact.source_revision
  → expected_source_revision = None

owner.operation REFRESH
  → ingress REFRESH
  → source_revision = fact.source_revision
  → expected_source_revision = fact.expected_source_revision

owner.operation CLOSE
  → ingress RESOLVE
  → source_revision = fact.source_revision
  → expected_source_revision = fact.expected_source_revision
```

Projectorがしてはいけないこと:

- Attention Store existence check
- prior Attention snapshot保持
- source_revision推測
- expected revision推測
- status文字列からowner lifecycleを再構成
- raw text / Provider payloadからoperation生成

Projectorはowner factが不正ならfail-closedでrejectする。

---

## 10. Attention Store CAS

Goal / Commitment / Activityはversioned stable sourceなので次を必須とする。

### OFFER

- currentに同じsource_refが存在しない
- expected_source_revisionはNone
- source_revisionあり

### REFRESH

- current source_ref存在
- `expected_source_revision == current.source_revision`
- `source_revision > current.source_revision`
- kind一致

### RESOLVE

- current source_ref存在
- `expected_source_revision == current.source_revision`
- `source_revision > current.source_revision`
- kind一致

stale / duplicate / future-base mismatchは完全no-commit。

### duplicate delivery

同じowner factのre-deliveryをsilent refreshとして扱わない。

- 同一`fact_id`はidempotent duplicateとしてreject/no-commit
- 同じ`source_revision`を別fact_idで再送してもnewerではないためreject/no-commit

consumer retryが必要ならowner event delivery層で同じfact identityを維持する。

---

## 11. Source-context envelope

owner lifecycle versionとglobal source contextを混ぜないため、Application境界は概念的に次を扱う。

```text
AttentionProjectionEnvelope[T]
- owner_fact: T
- source_context_revision
```

`source_context_revision`は既存authoritative context / Event envelope / Runtime snapshotから得る。

重要:

- owner factの`source_revision`をglobal contextへコピーしない。
- global contextの進行からowner operationを推測しない。
- long-running boundaryでは必要に応じてcommit直前のcurrent context freshness規則を別途適用する。

---

## 12. Event emission atomicity

owner lifecycle factは「mutation要求」ではなく「owner commit済みfact」である。

正規順序:

```text
validate owner transition
→ copy / reducer
→ owner current state atomic commit
→ lifecycle factを確定
→ lock外でEvent / Application boundaryへ渡す
```

owner lock内でAttention callback / runtime enqueueを行わない。

rollbackされたowner mutationからfactを公開しない。

Event publish失敗時にowner stateを巻き戻してはならない。必要ならoutbox/retryは別Infrastructure責務とし、同じfact identityを維持する。

---

## 13. 必須Regression

### Goal

1. new Goal rev N → OPEN
2. same Goal rev N→M → REFRESH / expected=N / source=M
3. Goal terminal rev M→T → CLOSE / expected=M / source=T
4. delayed REFRESH expected=N after current=M → stale reject
5. delayed CLOSE expected=N after current=M → stale reject
6. terminal factでFocus/Turn/obligation clearはCAS成功時だけ

### Commitment

1. new Commitment → OPEN
2. active/suspend等の更新 → REFRESH
3. released/fulfilled/violated → CLOSE
4. stale terminal → no-commit

### Activity

1. REQUESTED record → OPEN
2. ACCEPTED → REFRESH
3. STARTED → REFRESH
4. OBSERVABLE/APPLIED同一source継続 → REFRESH
5. same status + new effect_ref → record_revision進行 / REFRESH
6. COMPLETED → CLOSE
7. REJECTED / UNSUPPORTED / FAILED / CANCELLED / TIMED_OUT / SUPERSEDED → CLOSE
8. raw ActivityInvocation / Planからproject不可
9. stale CLOSE expected old revision → no-commit

### Cross-module

1. projectorはStoreをpollしない
2. owner source revisionとglobal source context revisionを混同しない
3. out-of-order owner factでAttention sourceを巻き戻さない
4. duplicate owner factでattention revision / fairness stateを進めない
5. owner mutation中にAttention / Runtime awaitを持たない

---

## 14. 既存contractへの反映方針

実装では次を行う。

### #366 Goal / Commitment

- owner-neutral `SourceLifecycleOperation`を共有contractから利用
- `GoalLifecycleProjectionFact` / `CommitmentLifecycleProjectionFact`をowner outputとして追加
- reducer/authority commit時のbefore/afterからfactを生成
-既存`AutonomyTrigger`は削除必須ではないが、#333 stable source lifecycle入力としては使用しない

### #329 Activity Execution

- `ActivityExecutionRecord.record_revision`追加
- owner commitごとにrevision進行
- `ActivityExecutionLifecycleFact`追加
- Foundation `ExecutionResult` status machineは変更しない

### #333 Attention

- projector入力を上記owner factsへ変更
- versioned stable sourceのREFRESH / RESOLVEでexpected revision CASを必須化
- lifecycle operationをStore existenceから推測しない

---

## 15. Gate

本書により、Codexが報告した「owner-side operation / source revision / expected source revision不足」は設計上解消した。

実装時に本書と実コードの間でさらにowner Authority不足が見つかった場合は推測実装せずSTOPする。

完了条件:

- 本書のtyped lifecycle factを実装
- #333 AmendmentのContinuation / Interrupt設計を実装
- Goal / Commitment / Activity lifecycle regression PASS
- Attention / Runtime adjacent PASS
- Ruff / strict Mypy / full pytest / compileall / diff-check PASS
- exact-head CI PASS
- ChatGPT exact-head再レビュー PASS
