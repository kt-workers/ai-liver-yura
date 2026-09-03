# V2 実行effect未確定性契約

Owner: #329
Consumer: #344
Related: #321 / #322 / #343 / #445
Status: Post-D10 Canonical Correction — 2026-09-04

## 1. 目的

#344 Plugin Integrationの実装前照合で、after-effect timeout/cancel時の「外部effectが起きた可能性はあるが、確認済みeffect evidenceはない」という状態について、#344が参照するclosed semanticsと#329 current contractの間に不整合が見つかった。

本書は、確認済みActual Effectと未確認のeffect可能性を分離し、Intent/Plan/timeoutだけからeffect successを捏造せずにActual Execution Factへ保持する契約を追加する。

本書は#329/#344の該当effect truth境界に対して優先する補足正本であり、既存`activity_execution_contracts.md`、`foundation_contracts.md`、`plugin_integration_contracts.md`の他のAuthority/lifecycle規則は維持する。

## 2. 確認済みeffectと未確認可能性を分離する

確認済みeffectは既存契約を維持する。

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

一方、effectが起きた可能性だけでは`ExecutionEffectEvidence`も`effect_ref`も生成しない。

未確認可能性は#329 owned closed state `ExecutionEffectUncertainty`で表す。

```text
NONE
UNKNOWN
POSSIBLY_APPLIED
```

意味:

- `NONE`: unresolvedなeffect不確定性を主張しない。これ単独では「外部effectが絶対に起きていない」という証明にはしない。
- `UNKNOWN`: Provider/Adapter結果だけでは、外部effectが発生したか判定できない。
- `POSSIBLY_APPLIED`: effect-capableな外部境界を越え、effectが適用された可能性があるが、確認済みevidenceはない。

`UNKNOWN` / `POSSIBLY_APPLIED`は成功factではなく、未確定性factである。

## 3. #329 Actual Fact aggregation

#329のcurrent `ActivityExecutionRecord`をActual Execution Fact aggregateとし、次を同時に保持する。

```text
ActivityExecutionRecord
- result: ExecutionResult
  - lifecycle status
  - confirmed effect_refs
- effect_uncertainty: ExecutionEffectUncertainty
```

Authorityは分離しない。`ActivityExecutionAuthority`だけがAdapter reportを検証し、confirmed effect refsとeffect uncertaintyをrecordへ確定する。

Plugin/Provider/Subsystemは`ActivityExecutionRecord`や`ExecutionResult`を直接構築・変更しない。

## 4. Adapter report

`ExecutionAdapterReport`は既存identity/status/effectsに加えて`effect_uncertainty`を返せる。

Rules:

- defaultは`NONE`。
- `UNKNOWN` / `POSSIBLY_APPLIED`は`FAILED / CANCELLED / TIMED_OUT` reportでだけ許可する。
- uncertaintyだけではnew `effect_ref`を作らない。
- 同じreportに確認済みeffect evidenceとunconfirmed uncertaintyが共存してよい。これは「確認済みeffectはあるが、追加effectについて未確定性が残る」場合を表す。
- `COMPLETED / OBSERVABLE / APPLIED` reportがunconfirmed uncertaintyを主張してはならない。

## 5. timeout / cancellation

### effect開始前と確定できる場合

preflight reject、permission revoke、stale descriptor、deadline before invoke、cancel before invoke等で外部effect開始前と確定できる場合:

```text
effect_refs = existing confirmed refs only
effect_uncertainty = NONE
```

### effect発生可能性が残る場合

Provider call開始後のtimeout/cancel/transport failure等でoutcome不明の場合:

```text
status = FAILED | CANCELLED | TIMED_OUT
effect_refs = confirmed refs only
effect_uncertainty = UNKNOWN | POSSIBLY_APPLIED
```

`not applied`やsuccessを捏造しない。自動retryで二重effectを起こさない。

## 6. 確認済みeffectの保持

report確定前にeffectが確認できた場合は、既存#329契約どおり`OBSERVABLE/APPLIED` evidenceを先にrecordし、その後terminalへ閉じても`effect_refs`を保持する。

terminal resultに`effect_uncertainty`が存在しても、既存のconfirmed `effect_refs`を削除・downgradeしない。

## 7. terminal後の外界確認

current V2の`ExecutionResult` terminal lifecycleは再openしない。

`ActivityExecutionPort.execute()`がreturnして#329がterminal factを確定した**後**に新しい外界確認が到着した場合、その確認を旧Executionへ直接後付けする暗黙経路は作らない。

必要な場合は、explicit readback/reconciliation Activityを新しいcommand/invocationとして#329経路で実行し、original `command_id / dispatch_id / plugin_id / plugin_generation`をtyped provenanceとして参照する。

これにより:

- terminal lifecycleを隠れて再openしない。
- old plugin generationのlate signalをnew generation executionへ混ぜない。
- readbackそのものもActual Execution Fact Authorityを通る。

#344はpost-terminal callbackから#329 private stateを直接mutationしてはならない。

## 8. Plugin Integrationへの適用

#344のafter-effect ambiguous caseは次へ置換する。

```text
confirmed OBSERVABLE/APPLIED
→ ExecutionEffectEvidence + effect_refs

unconfirmed outcome
→ ExecutionEffectUncertainty.UNKNOWN / POSSIBLY_APPLIED
```

旧`plugin_integration_contracts.md` §6の「`UNKNOWN / POSSIBLY_APPLIED / APPLIED`等を#329 closed effect semanticsへ投影する」という記述は、本書の二層表現で具体化する。

## 9. 必須回帰

Foundation / #329:
- REQUESTED/ACCEPTED/STARTED/COMPLETEDでunconfirmed uncertaintyを捏造しない。
- TIMED_OUT + POSSIBLY_APPLIED + effect_refsなしをtypedに保持できる。
- confirmed effect_refsを保持したままterminal uncertaintyを持てる。
- invalid status + uncertaintyをfail-closedする。
- Event projectionへeffect uncertaintyを含める。

#344:
- cancel/timeout before invokeは`NONE`。
- after-effect timeoutは`POSSIBLY_APPLIED`、fake effect_refなし。
- permission revoke / STOPPING final-use fenceでinvoke前に閉じる場合は`NONE`。
- retryによる二重effectを作らない。

## 10. 完了条件

- #329 canonicalとproduction typeが同じclosed stateを持つ。
- #344が存在しない#329 semanticsを参照しない。
- confirmed effectとunconfirmed possibilityを混同しない。
- Plugin専用のparallel Actual Fact Authorityを作らない。
- post-terminal confirmationを旧Executionへ暗黙mutationしない。
