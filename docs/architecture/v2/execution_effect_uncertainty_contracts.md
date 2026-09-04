# V2 実行作用（effect）の未確定性契約

Owner: #329
Consumer: #344
Related: #321 / #322 / #343 / #445
Status: Post-D10 Canonical Correction — 2026-09-04

## 1. 目的

#344のプラグイン統合（Plugin Integration）の実装前照合で、外部作用の発生後にタイムアウトまたは取消となった場合の「外部作用が起きた可能性はあるが、確認済みの作用証拠（effect evidence）はない」という状態について、#344が前提とする閉じた意味集合と#329の現行契約が一致していないことが判明した。

本書は、確認済みの実際の作用（Actual Effect）と未確認の作用可能性を分離し、意図（Intent）・計画（Plan）・タイムアウトだけから作用成功を捏造せず、実行実績事実（Actual Execution Fact）へ保持する契約を追加する。

本書は#329 / #344の該当する作用事実境界に対して優先する補足正本であり、既存`activity_execution_contracts.md`、`foundation_contracts.md`、`plugin_integration_contracts.md`の他の判断権限（Authority）・ライフサイクル（lifecycle）規則は維持する。

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
= #329の判断権限（Authority）が検証済み証拠（evidence）からだけ導出する単調増加（monotonic）参照
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
- `POSSIBLY_APPLIED`: 作用を起こし得る外部境界を越え、作用が適用された可能性があるが、確認済み証拠（evidence）はない。

`UNKNOWN` / `POSSIBLY_APPLIED`は成功事実ではなく、未確定性の事実である。

## 3. #329 実行実績事実の集約

#329の現行`ActivityExecutionRecord`を実行実績事実（Actual Execution Fact）の集約（aggregate）とし、次を同時に保持する。

```text
ActivityExecutionRecord
- result: ExecutionResult
  - lifecycle status
  - confirmed effect_refs
- effect_uncertainty: ExecutionEffectUncertainty
```

判断権限（Authority）は分離しない。`ActivityExecutionAuthority`だけがアダプター報告（Adapter report）を検証し、確認済み`effect_refs`と`effect_uncertainty`をrecordへ確定する。

Plugin / Provider / Subsystemは`ActivityExecutionRecord`や`ExecutionResult`を直接構築・変更しない。

## 4. アダプター報告

`ExecutionAdapterReport`は既存の識別情報（identity）・状態（status）・作用証拠（effects）に加えて`effect_uncertainty`を返せる。

規則:

- 既定値は`NONE`。
- `UNKNOWN` / `POSSIBLY_APPLIED`は`FAILED / CANCELLED / TIMED_OUT`の終端失敗報告でだけ許可する。
- 未確定性（uncertainty）だけでは新しい`effect_ref`を作らない。
- `COMPLETED / OBSERVABLE / APPLIED`の報告が未確認の`effect_uncertainty`を主張してはならない。
- 終端失敗報告は既存#329規則どおり新しい作用証拠（effect evidence）を導入しない。
- 確認済み作用と追加の未確認`effect_uncertainty`が同じ実行に存在する場合、`OBSERVABLE / APPLIED`の報告で確認済み作用を先に確定し、その後`FAILED / CANCELLED / TIMED_OUT`の報告で未確定性を記録する。1つの終端報告へ新しい確認済み作用（confirmed effect）と未確定性を混載しない。

## 5. タイムアウト / 取消

### 作用開始前と確定できる場合

事前確認（preflight）での拒否、権限（permission）取消、古いdescriptor、呼出し（invoke）前の期限到来（deadline）、呼出し前の取消（cancel）等で外部作用開始前と確定できる場合:

```text
effect_refs = existing confirmed refs only
effect_uncertainty = NONE
```

### 作用発生可能性が残る場合

Provider呼出し開始後のタイムアウト・取消・通信失敗（transport failure）等で結果が不明な場合:

```text
status = FAILED | CANCELLED | TIMED_OUT
effect_refs = existing confirmed refs only
effect_uncertainty = UNKNOWN | POSSIBLY_APPLIED
```

「適用されていない」ことや成功（success）を捏造しない。自動再試行（retry）で二重作用を起こさない。

## 6. 確認済み作用の保持

報告（report）の確定前に作用を確認できた場合は、既存#329契約どおり`OBSERVABLE / APPLIED`の証拠（evidence）を先にrecordし、その後終端（terminal）へ閉じても`effect_refs`を保持する。

終端結果（terminal result）に`effect_uncertainty`が存在しても、既存の確認済み`effect_refs`を削除・格下げ（downgrade）しない。

## 7. 終端後の外界確認

現行V2の`ExecutionResult`は、終端後のライフサイクル（terminal lifecycle）を再開（reopen）しない。

`ActivityExecutionPort.execute()`が返却（return）し、#329が終端事実（terminal fact）を確定した**後**に新しい外界確認が到着した場合、その確認を旧Executionへ直接後付けする暗黙経路は作らない。

必要な場合は、明示的な再読取・整合（readback / reconciliation）Activityを新しいcommand / invocationとして#329経路で実行し、元の`command_id / dispatch_id / plugin_id / plugin_generation`を型付き由来情報（typed provenance）として参照する。

これにより:

- 終端ライフサイクル（terminal lifecycle）を隠れて再開（reopen）しない。
- 旧plugin世代（old plugin generation）の遅延signalを新世代の実行へ混ぜない。
- 再読取（readback）そのものも実行実績事実の判断権限（Actual Execution Fact Authority）を通る。

#344は終端後callback（post-terminal callback）から#329のprivate stateを直接変更（mutation）してはならない。

## 8. プラグイン統合への適用

#344で外部作用発生後の結果が不明な場合は、次の二層表現へ置換する。

```text
confirmed OBSERVABLE/APPLIED
→ ExecutionEffectEvidence + effect_refs

unconfirmed outcome
→ ExecutionEffectUncertainty.UNKNOWN / POSSIBLY_APPLIED
```

旧`plugin_integration_contracts.md` §6の「`UNKNOWN / POSSIBLY_APPLIED / APPLIED`等を#329の閉じた作用意味集合（closed effect semantics）へ投影する」という記述は、本書の二層表現で具体化する。

## 9. 必須回帰

Foundation / #329:
- REQUESTED / ACCEPTED / STARTED / COMPLETEDで未確認の`effect_uncertainty`を捏造しない。
- TIMED_OUT + POSSIBLY_APPLIED + effect_refsなしを型付きで保持できる。
- 確認済み`effect_refs`を保持したまま終端時の未確定性を持てる。
- 不正な状態（invalid status）と未確定性の組合せを安全側で拒否（fail-closed）する。
- Eventへの投影（projection）へ作用の未確定性を含める。
- Adapter開始後の取消（cancel）・例外（exception）で未確定性を失わない。
- Adapter開始後の空・不正・識別子不一致の報告契約違反でも`UNKNOWN`を保持する。
- Adapter開始前の取消（cancel）では`NONE`を維持する。

#344:
- 呼出し（invoke）前の取消・タイムアウトは`NONE`。
- 外部作用発生後のタイムアウトは`POSSIBLY_APPLIED`とし、偽の`effect_ref`を作らない。
- 権限取消（permission revoke）または`STOPPING`の最終使用境界（final-use fence）で呼出し前に閉じる場合は`NONE`。
- 再試行（retry）による二重作用を作らない。

## 10. 完了条件

- #329の正本（canonical）とproduction typeが同じ閉じた状態集合（closed state）を持つ。
- #344が存在しない#329の意味規則（semantics）を参照しない。
- 確認済み作用（confirmed effect）と未確認可能性（unconfirmed possibility）を混同しない。
- Plugin専用の並行する実績事実判断権限（parallel Actual Fact Authority）を作らない。
- 終端後確認（post-terminal confirmation）を旧Executionへ暗黙に変更（mutation）しない。
