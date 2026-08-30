# V2 Multi-owner Snapshot Consistency Contracts

Owners: #321 / #322
Consumers: #326 / #327 / #328 / #331 / #337 / #338 / #339 and any contract requiring a version-stabilized composite read
Design gate: #445 D10
Status: Shared Canonical Supplement / implementation-decidability correction

## 1. 目的

複数ownerのimmutable snapshotを一貫したlogical cutとして読む際に使われる「bounded retry / version-stabilized read」を共通化し、各Module実装がretry回数、比較対象、sleep/backoff、失敗時fallbackを独自に決めないようにする。

本書は各ownerのState Authorityを統合しない。一つのglobal revisionも導入しない。

## 2. SnapshotStabilizationPolicy

```text
SnapshotStabilizationPolicy
- policy_id: non-empty stable identity
- policy_revision: non-negative int
- max_attempts: int >= 1
- allow_event_loop_yield_between_attempts: bool
```

`max_attempts`は最初のread cycleを含む総試行回数。

Initial V2 baseline:

```text
policy_id = v2.snapshot-stabilization.default
policy_revision = 1
max_attempts = 3
allow_event_loop_yield_between_attempts = true
```

policy変更はrevisionを進める。consumer codeに別hidden attempt数を持たない。

## 3. Canonical stabilization algorithm

各consumer contractが列挙するowner/read順を一つの`read_cycle()`とする。

1 attempt:

```text
before generation/read fence
→ required owner snapshots in canonical consumer-defined order
→ same owner snapshots/fence re-read required by consumer
→ after generation/read fence
→ equality/revision validation
```

PASSなら即return。

FAILなら:

- attempt < max_attempts の場合だけ再試行。
- `allow_event_loop_yield_between_attempts=true`かつasync orchestrationの場合、**高々1回のevent-loop cooperative yield**を挟んでよい。実時間sleep/backoffを入れない。
- cooperative yieldは他taskへ実行機会を渡す契約であり、他taskがさらに別のawait/yieldを必要とする場合の完了までは保証しない。
- `false`なら直ちに次read cycle。
- max attempt失敗後はtyped `SNAPSHOT_INCOHERENT` / owner-specific equivalentとしてfail-closed。

## 4. What counts as the same generation

各owner snapshotについてconsumer canonicalが要求するidentityを比較する。

最低限:

- owner-native revision
- owner-specific generation/policy/model/definition revision where declared
- same revisionでpayload equalityがcontract上必要ならimmutable equality

禁止:

- revisionが近いから同世代とみなす
- source_context_revisionだけ一致してowner-native revision差を無視する
- old cached snapshotをlatest扱いする
- timestamp近似でgenerationを判定する

## 5. Policy generation

stable read自身がpolicy ownerを読む場合、stabilization policy identity/revisionも取得generationへbindする。

read中にstabilization policy revisionが変わった場合、そのattemptは不成立。old attempt counterをnew policyへ引き継がず、新operation generationとして開始する。

## 6. Lock / await boundary

- Core-global lock禁止。
- Provider/LLM/network/DB callをread fence内へ入れない。
- ownerがasync read Portを必要とする場合も、current immutable snapshot readだけに限定しlong-running external I/Oを行わない。
- stabilization failureを解消するためにunbounded spinしない。

## 7. Failure semantics

max attemptsでstable setを得られない場合:

- old/capture-time snapshotへfallbackしない。
-各owner値を混ぜたpartial compositeをsuccessとして返さない。
- current meaning/state/decision/pose等を補作しない。
- consumerがoptional inputを明示degradeできる契約なら、そのoptional inputだけunavailableとして扱える。
- required inputならoperationをfail-closedする。

## 8. Consumer-specific ordering remains local

本書はread順そのものを一律にしない。

例:
- #337はglobal source fence → State → Attention → Character → Projection Policy → re-read → global fence。
- #327 Deep Appraisalはsource context + Internal State pair。
- #328 Executiveはsource/goal/attention/internal state + capability/precondition live commit state。
- #331 Speech Performanceはsource/state/attention/Character/projection policy。

各consumerは「何を同時にstableにする必要があるか」を自身のcanonicalで列挙し、本書は**retry mechanics**だけを共有する。

## 9. Required tests

- first attempt stable success
- first unstable / second stable success
- 3 attemptsすべてunstableでfail-closed
- max_attempts=1
- policy invalid/0/bool reject
- event-loop yield有無でsemantic result不変
- cooperative yield時にunrelated taskへ少なくとも1回の実行機会を渡し、追加awaitの完了までは要求しない
- same owner revision + different immutable payloadをinvariant violation
- policy revision mid-readでold/new generationを混ぜない
- failure時capture-time fallbackなし
- unrelated async workをglobal lock/spinでstarveしない

## 10. Production implementation mapping

D10後の共有実装は次を正本実装とする。

- `app/domain/contracts/snapshots.py`
  - `SnapshotStabilizationPolicy`
  - `SnapshotGenerationSample`
  - `SnapshotReadCycle`
  - sync / async bounded stabilizer
  - `SNAPSHOT_INCOHERENT` fail-closed
  - same revisionでpayload/generationが変化した場合のinvariant violation
- `tests/domain/contracts/test_snapshot_consistency.py`
  - 本書Section 9の共有mechanicsを直接検証する。

consumer固有のread順・optional degradation・owner-specific generation identityは各consumer ownerの
実装責務として残し、共有stabilizerがそれらのAuthorityを奪わない。
