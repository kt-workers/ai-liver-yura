# V2 実行作用（effect）の未確定性契約

Owner: #329
Consumer: #344
Related: #321 / #322 / #343 / #445
Status: Post-D10 Canonical Correction — 2026-09-04

## 1. 目的

#344 Plugin Integrationの実装前照合で、外部作用の発生後にtimeout / cancelとなった場合の「外部作用が起きた可能性はあるが、確認済みの作用証拠（effect evidence）はない」という状態について、#344が前提とする閉じた意味集合と#329の現行契約が一致していないことが判明した。

本書は、確認済みの実際の作用（Actual Effect）と未確認の作用可能性を分離し、Intent / Plan / timeoutだけから作用成功を捏造せずにActual Execution Factへ保持する契約を追加する。

本書は#329 / #344の該当する作用事実境界に対して優先する補足正本であり、既存`activity_execution_contracts.md`、`foundation_contracts.md`、`plugin_integration_contracts.md`の他のAuthority / lifecycle規則は維持する。

## 2. 確認済み作用と未確認可能性を分離する

確認済み作用は既存契約を維持する。

```text
ExecutionEffectEvidence
- effect_id
- capability_id
- descriptor_revision
- operation_ref
- kind = OBSERVABLE | APPLIED
- payload

ExecutionResult.effect_refs
= #329 Authorityが検証済みevidenceからだけ導出するmonotonic参照
```

一方、作用が起きた可能性だけでは`ExecutionEffectEvidence`も`effect_ref`も生成しない。

未確認可能性は#329が所有する閉じた状態集合（closed state）`ExecutionEffectUncertainty`で表す。

```text
NONE
UNKNOWN
POSSIBLY_APPLIED
```

意味:

- `NONE`: 未解決の作用不確定性を主張しない。これ単独では「外部作用が絶対に起きていない」という証明にはしない。
- `UNKNOWN`: Provider / Adapterの結果だけでは、外部作用が発生したか判定できない。
- `POSSIBLY_APPLIED`: 作用を起こし得る外部境界を越え、作用が適用された可能性があるが、確認済みevidenceはない。

`UNKNOWN` / `POSSIBLY_APPLIED`は成功factではなく、未確定性factである。

## 3. #329 Actual Fact aggregation

#329の現行`ActivityExecutionRecord`をActual Execution Factのaggregateとし、次を同時に保持する。

```text
ActivityExecutionRecord
- result: ExecutionResult
  - lifecycle status
  - confirmed effect_refs
- effect_uncertainty: ExecutionEffectUncertainty
```

Authorityは分離しない。`ActivityExecutionAuthority`だけがAdapter reportを検証し、確認済みeffect refsとeffect uncertaintyをrecordへ確定する。

Plugin / Provider / Subsystemは`ActivityExecutionRecord`や`ExecutionResult`を直接構築・変更しない。

## 4. Adapter report

`ExecutionAdapterReport`は既存identity / status / effectsに加えて`effect_uncertainty`を返せる。

Rules:

- defaultは`NONE`。
- `UNKNOWN` / `POSSIBLY_APPLIED`は`FAILED / CANCELLED / TIMED_OUT`の終端失敗reportでだけ許可する。
- uncertaintyだけでは新しい`effect_ref`を作らない。
- `COMPLETED / OBSERVABLE / APPLIED` reportが未確認のuncertaintyを主張してはならない。
- 終端失敗reportは既存#329規則どおり新しいeffect evidenceを導入しない。
- 確認済み作用と追加の未確認uncertaintyが同じ実行に存在する場合、`OBSERVABLE / APPLIED` reportで確認済み作用を先に確定し、その後`FAILED / CANCELLED / TIMED_OUT` reportでuncertaintyを記録する。1つの終端reportへ新規confirmed effectとuncertaintyを混載しない。

## 5. timeout / cancellation

### 作用開始前と確定できる場合

事前確認（preflight）での拒否、permission取消、stale descriptor、invoke前のdeadline、invoke前のcancel等で外部作用開始前と確定できる場合:

```text
effect_refs = existing confirmed refs only
effect_uncertainty = NONE
```

### 作用発生可能性が残る場合

Provider call開始後のtimeout / cancel / transport failure等で結果が不明な場合:

```text
status = FAILED | CANCELLED | TIMED_OUT
effect_refs = existing confirmed refs only
effect_uncertainty = UNKNOWN | POSSIBLY_APPLIED
```

「適用されていない」ことやsuccessを捏造しない。自動retryで二重作用を起こさない。

## 6. 確認済み作用の保持

report確定前に作用を確認できた場合は、既存#329契約どおり`OBSERVABLE / APPLIED` evidenceを先にrecordし、その後terminalへ閉じても`effect_refs`を保持する。

terminal resultに`effect_uncertainty`が存在しても、既存のconfirmed `effect_refs`を削除・downgradeしない。

## 7. terminal後の外界確認

現行V2の`ExecutionResult` terminal lifecycleは再openしない。

`ActivityExecutionPort.execute()`がreturnして#329がterminal factを確定した**後**に新しい外界確認が到着した場合、その確認を旧Executionへ直接後付けする暗黙経路は作らない。

必要な場合は、明示的なreadback / reconciliation Activityを新しいcommand / invocationとして#329経路で実行し、元の`command_id / dispatch_id / plugin_id / plugin_generation`をtyped provenanceとして参照する。

これにより:

- terminal lifecycleを隠れて再openしない。
- old plugin generationのlate signalをnew generation executionへ混ぜない。
- readbackそのものもActual Execution Fact Authorityを通る。

#344はpost-terminal callbackから#329 private stateを直接mutationしてはならない。

## 8. Plugin Integrationへの適用

#344で外部作用発生後の結果が不明な場合は、次の二層表現へ置換する。

```text
confirmed OBSERVABLE/APPLIED
→ ExecutionEffectEvidence + effect_refs

unconfirmed outcome
→ ExecutionEffectUncertainty.UNKNOWN / POSSIBLY_APPLIED
```

旧`plugin_integration_contracts.md` §6の「`UNKNOWN / POSSIBLY_APPLIED / APPLIED`等を#329 closed effect semanticsへ投影する」という記述は、本書の二層表現で具体化する。

## 9. 必須回帰

Foundation / #329:
- REQUESTED / ACCEPTED / STARTED / COMPLETEDで未確認uncertaintyを捏造しない。
- TIMED_OUT + POSSIBLY_APPLIED + effect_refsなしをtypedに保持できる。
- confirmed effect_refsを保持したままterminal uncertaintyを持てる。
- invalid status + uncertaintyをfail-closedする。
- Event projectionへeffect uncertaintyを含める。
- Adapter開始後のcancel / exceptionでuncertaintyを失わない。
- Adapter開始前のcancelでは`NONE`を維持する。

#344:
- invoke前のcancel / timeoutは`NONE`。
- 外部作用発生後のtimeoutは`POSSIBLY_APPLIED`、fake `effect_ref`なし。
- permission revoke / STOPPING final-use fenceでinvoke前に閉じる場合は`NONE`。
- retryによる二重作用を作らない。

## 10. 完了条件

- #329 canonicalとproduction typeが同じclosed stateを持つ。
- #344が存在しない#329 semanticsを参照しない。
- confirmed effectとunconfirmed possibilityを混同しない。
- Plugin専用のparallel Actual Fact Authorityを作らない。
- post-terminal confirmationを旧Executionへ暗黙mutationしない。
