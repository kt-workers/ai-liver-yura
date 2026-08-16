# Attention / Autonomy / Turn 設計訂正 — 2026-08-16

Status: **Canonical Amendment / Issue #333**

Applies to:
- `docs/architecture/v2/attention_turn_contracts.md`
- `docs/architecture/v2/brain_architecture.md`
- `docs/architecture/v2/concurrency_architecture.md`
- `docs/architecture/v2/goal_commitment_architecture.md`

## 1. 正本順位と訂正範囲

本書は Issue #333 の詳細正本 `attention_turn_contracts.md` に対する設計訂正である。

本書は次の2点について、既存文書の曖昧な記述を **supersede** する。

1. current foreground / current turn / response obligation の継続と、別sourceによるinterruptを同じthreshold判定へ入れていた点
2. `resolve` が、更新済みsourceへ遅延到着した古い終了factを適用しないためのsource-version CAS契約を持っていなかった点

上記2点以外のAuthority、budget、fairness、Speech #348境界、Runtime非blocking、Design → Code原則は既存 `attention_turn_contracts.md` を維持する。

特に、既存設計の `offer / refresh / resolve` lifecycleそのものは変更しない。同一stable `source_ref` の後続更新は `refresh`、終了は `resolve` である。

---

## 2. 設計訂正A — Continuation と Interrupt を分離する

### 2.1 問題

従来の `interruption threshold` は challenger source がcurrent foregroundへ割り込む条件として定義したが、次を明示的に分離していなかった。

- current foreground source自身の継続的な再評価
- current turn / response obligationを満たすための継続
- foregroundが存在しないidle状態からの新しい開始
- 別sourceがcurrent foreground / protected turnへ割り込むinterrupt

この4つを同一のinterrupt判定へ入れてはならない。

例えばcurrent foregroundがNORMALのGameで、そのGame自身の新しいsalient eventを評価する場合、それはNORMAL challengerがNORMAL foregroundへ割り込むことではない。**同じforegroundのcontinuation**である。

### 2.2 Claim relation

#333はclaim候補ごとに、current Attention stateとの関係を次のclosed typed relationへ分類する。

```text
AttentionClaimRelation
- obligation_continuation
- foreground_continuation
- idle_start
- challenger_interrupt
```

意味:

#### `obligation_continuation`

candidate `source_ref` がactiveな `current_turn_owner` または `response_obligation` と一致し、そのturn / obligationを継続して扱う候補。

これはinterruptではない。

#### `foreground_continuation`

candidate `source_ref == foreground_focus_ref` であり、current foregroundそのものを再評価・継続する候補。

これはinterruptではない。

#### `idle_start`

active foregroundがなく、かつ後述するprotected direct-user turn / obligationも存在しない状態で、新しいsourceをExecutive triggerとして開始する候補。

これはinterruptではない。

#### `challenger_interrupt`

上記いずれにも該当せず、別sourceとしてcurrent foregroundまたはprotected turn / obligationへ割り込み得る候補。

**interruption thresholdを適用するのはこのrelationだけ**とする。

### 2.3 Direct-user protected turn

foregroundの有無とは独立に、次を `protected_direct_user_refs` とする。

```text
protected_direct_user_refs = {
  current_turn_owner,
  response_obligation
}
のうち、current active AttentionSourceとして存在し、
effective_priority == DIRECT_USER のref
```

`protected_direct_user_refs` が1件以上存在する間:

- そのref自身は `obligation_continuation` としてclaim可能
- 別のDIRECT_USER sourceは `challenger_interrupt` としてDIRECT_USER thresholdを満たせばclaim可能
- NORMAL / FOREGROUND / BACKGROUND sourceはmonitor / future eligibilityとして保持できるが、foregroundの有無にかかわらずExecutive dispatch claim不可
- current foregroundがGame等のlower priority sourceであっても、direct-user obligationを差し置いてcontinuation claimしてはならない

したがって、**direct-user turn保護は `foreground_focus_ref` が `None` でも有効**である。

### 2.4 Effective protected priority

interrupt判定に用いる保護priorityはforegroundだけから決めない。

```text
protected priorities =
- active foreground source priority
- active current_turn_owner source priority
- active response_obligation source priority
```

このうち、candidate自身のcontinuation対象を除いた最大priorityを `effective_protected_priority` とする。

ただし `protected_direct_user_refs` が存在する場合、effective protectionは最低でもDIRECT_USERとして扱う。

`challenger_interrupt` は、`AttentionSchedulingPolicy.interruption_thresholds` が要求するminimum challenger priority以上の場合だけclaim可能。

### 2.5 Claimabilityとfairnessの順序

fairnessは「本来claimできないsourceを選ぶ」Authorityではない。

正規順序:

```text
active / freshness / expiry validation
→ claim relation分類
→ protected turn / interruption gate
→ claimable set確定
→ cooldown / same-source fairness / priority-burst fairness
→ atomic claim
→ Executive enqueue
```

禁止:

```text
all eligible sourceへfairness適用
→ lower priorityを1件へ絞る
→ その1件がinterrupt不可
→ claimable continuationまで消える
```

fairnessは**claimable set内だけ**で作用する。

そのため、priority burst上限へ到達してもlower sourceがprotected turnのためclaim不可なら、claim可能なcurrent continuationを不必要に停止しない。

### 2.6 Trigger contract

`ExecutiveTriggerEligibility` は「interrupt可能か」というboolだけでclaim全体を表現しない。

実装contractは少なくとも次の意味を区別する。

```text
ExecutiveTriggerEligibility
- ... existing revision / source fields
- claim_relation: AttentionClaimRelation
- interruption_allowed
```

規則:

- `interruption_allowed` は `challenger_interrupt` にだけ意味を持つ
- `foreground_continuation` / `obligation_continuation` / `idle_start` は `interruption_allowed == False` でも通常dispatch可能
- `AttentionCoordinator` は `interruption_allowed` を全trigger共通のdispatch gateとして使用しない
- `challenger_interrupt` はthreshold PASSしたものだけ `claim_next()` が返す
- Speech #348への `request_interrupt` は `claim_relation == challenger_interrupt` かつ必要条件を満たす場合だけ生成可能

これにより「Executiveを起動してよい」と「現在Activity/Speechへinterruptを要求してよい」を分離する。

### 2.7 必須反例

Unit / Adjacentで最低限次を固定する。

1. current foreground NORMAL source自身のupdate → `foreground_continuation` としてclaim可能
2. current foreground FOREGROUND source自身のupdate → thresholdを要求せずclaim可能
3. DIRECT_USER response obligationあり + `foreground_focus_ref=None` + NORMAL/FOREGROUND/BACKGROUND待機 → lower sourceはclaim不可
4. DIRECT_USER obligation中でも別DIRECT_USER sourceはpolicyの範囲でinterrupt候補になり得る
5. protected interval中、priority burst上限到達を理由にnon-claimable lower sourceへ切替えず、claimable continuationを失わない
6. obligation解除後は通常のpriority / fairnessへ復帰
7. continuation triggerからSpeech `request_interrupt`を生成しない

---

## 3. 設計訂正B — `resolve` をsource-version CASにする

### 3.1 問題

stable `source_ref` を複数revisionにわたってrefreshするsourceでは、遅延到着した古い`resolve`が最新sourceを削除してはならない。

例:

```text
Goal source revision 4 admitted
→ refresh revision 5 committed
→ network / lane delayした "resolve revision 4" 到着
```

この古いresolveでrevision 5 source、foreground、turn、response obligationをclearするのは禁止する。

`source_context_revision`のglobal monotonic checkだけではこの競合を閉じられない。

### 3.2 Versioned stable source

同じ`source_ref`をowner lifecycle中に再利用し、`refresh` / `resolve`され得るsourceを **versioned stable source** とする。

代表:

- Goal
- Commitment
- Activity execution lifecycle
- 長時間Streaming session / Game session等、同じrefを更新するsource

versioned stable sourceはowner側のmonotonic `source_revision` を必須とする。

一方、event/candidate ID自体が一意で後続refreshを持たないone-shot sourceはunversionedでもよい。

### 3.3 Resolve CAS fields

`AttentionIngressSignal` のversion契約を次のように補強する。

```text
AttentionIngressSignal
- ... existing fields
- source_revision?
- expected_source_revision?
```

意味:

- `source_revision`: incoming source fact自身のrevision
- `expected_source_revision`: このmutationが前提とするcurrent AttentionSource revision

`expected_source_revision` はCASのexpected valueであり、incoming revisionと同じ意味ではない。

### 3.4 Operation別規則

#### OFFER

- sourceが未存在であること
- versioned stable sourceならinitial `source_revision`を持つ
- `expected_source_revision`は持たない

#### REFRESH

既存のrefresh/coalesce contractを維持する。

versioned stable sourceでは:

- current sourceが存在する
- incoming `source_revision`はcurrentより古くできない
- owner contractがbase revisionを提供できる場合は`expected_source_revision`でCASしてよい
- stale refreshでcurrent sourceを巻き戻さない

#### RESOLVE

versioned stable sourceでは `expected_source_revision` を必須とする。

commit条件:

```text
signal.expected_source_revision == current_source.source_revision
```

不一致なら **stale resolveとしてfail-closed**。

terminal fact自身が次revisionを持つ場合:

```text
current source revision = 5
terminal fact source_revision = 6
resolve expected_source_revision = 5
```

は合法。

したがってincoming terminal revisionとexpected current revisionは別fieldで表す。

禁止例:

```text
current source revision = 5
resolve expected_source_revision = 4
→ stale reject

current source revision = 5
resolve expected_source_revision = 6
→ future/base mismatch reject
```

### 3.5 Unversioned one-shot source

one-shot sourceは同じ`source_ref`をrefreshして別世代へ進めないことを前提とする。

unversioned sourceをresolveする場合:

- exact `source_ref`がcurrent sourceに存在すること
- resolve `occurred_at` がcurrent `last_refreshed_at`より古くないこと
- sourceが実際にはstable lifecycleを持つならunversioned運用を禁止し、versioned stable sourceへ昇格する

「stable sourceだがrevisionを持たない」ことでCASを迂回してはならない。

### 3.6 Atomicity

stale / future mismatch resolveは:

- sourceを削除しない
- `foreground_focus_ref`をclearしない
- `active_focus_intent_ref`をclearしない
- `current_turn_owner`をclearしない
- `response_obligation`をclearしない
- cooldownを変更しない
- attention revisionを進めない
- selection / fairness stateを変更しない

つまり**完全なno-commit**である。

合法resolveだけがsource削除と、そのsourceを参照するFocus/Turn/obligationのclearを同一atomic mutationで行う。

### 3.7 Projector責務

Application/Usecase projectorはsource ownerのtyped lifecycle factからversion情報を欠落させない。

- ownerがstable lifecycle sourceなら `source_revision` をAttentionへ搬送する
- terminal transitionがbase/current revisionを持つなら `expected_source_revision` を搬送する
- Attention projectorがStoreをpollしてexpected revisionを推測しない
- raw text、provider payload、wall clockからrevisionを作らない

Source owner側に必要なbase revisionが存在しない場合は、実装を推測せずそのowner contractの設計不備としてSTOPする。

### 3.8 必須反例

1. current source rev4 → refresh rev5 → delayed resolve expected rev4 → stale reject、State完全不変
2. current source rev5 → terminal fact rev6 / expected rev5 → resolve成功
3. current source rev5 → resolve expected rev6 → reject
4. stale resolveでforeground/turn/response obligationがclearされない
5. stale resolveでattention revisionが進まない
6. one-shot sourceの古い`occurred_at` resolve → reject
7. stable lifecycle sourceをrevisionなしでresolveするpathが存在しない

---

## 4. 既存設計との整合

この訂正でAuthorityは変更しない。

- Executive #328: conscious Goal / Action / deliberate focus shift
- Attention #333: scheduling / Focus / Turn / claim relation / interrupt eligibility
- Goal #366: Goal / Commitment state
- Activity #329: execution fact
- Speech #348: speech candidate lifecycle / actual interruption effect
- Runtime #322: lane / queue / cancellation primitives

`foreground_continuation`を追加しても、#333がGoal/Actionを決めるわけではない。これは「同じfocus sourceからExecutiveを再評価してよい」というscheduling factである。

`resolve` CASを追加しても、#333がsource ownerのlifecycleを決めるわけではない。ownerが発行したtyped version/factを、stale mutationなしでAttention stateへ反映するだけである。

---

## 5. 実装Gate

この訂正文書作成後、Codexは同一Issue #333 / 同一branch / PR #412でDesign → Codeを行う。

実装前提:

- 本書を読み、既存`attention_turn_contracts.md`の該当曖昧箇所より本書を優先する
- continuation / interruptをbool一つへ潰さない
- resolve freshnessをglobal context revisionだけで代用しない
- Source owner contractに不足があれば推測せず報告する

完了条件:

- 上記反例Unit PASS
- Attention / Runtime adjacent PASS
- Ruff / strict Mypy / full pytest / compileall / diff-check PASS
- exact-head CI PASS
- ChatGPT exact-head再レビュー PASS

本書は上記2件が`attention_turn_contracts.md`本体へ統合されるまでcanonical amendmentとして有効である。
