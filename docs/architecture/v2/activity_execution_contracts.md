# Activity / Execution Authority 型付き契約

## 1. 目的

この文書はIssue #329の実装正本である。Executiveが確定した`SystemCommand`または後続#361のtyped Plan stepを、Capability選択、preflight、非同期dispatch、Actual Execution Factまで接続する。

Intent、Plan、Provider応答を実行済みfactとして扱わない。Foundation `ExecutionResult`をActual Fact lifecycleの唯一の正本とし、重複するActivity status machineは作らない。

## 2. Authority境界

- #328 Executiveは「何をするか」を選び、`SystemCommand`を発行する。
- #366 Goal Storeはcurrent Goal/Commitmentを所有する。Activity失敗・完了だけでGoalを直接変更しない。
- #361 Plannerは複雑Goalのstep構造を作るが、実行済みfactを作らない。
- #329 `ActivityExecutionAuthority`はcommand admission、Capability binding、preflight、execution lifecycle、Actual Effect参照を所有する。
- Capability Provider / Plugin / Speech / Body / Subsystem Adapterは外部処理を行いtyped reportを返すが、`ExecutionResult`を直接構築・確定しない。
- Appraisal、Executive、Goal、Characterは確定済みexecution snapshotを読むだけで、履歴を改変しない。

Goal/Commitment transitionとAttention intentはActivity dispatch対象ではない。Speech、Body、Activity、Plugin、Systemの実行可能intentだけを受理する。

## 3. Invocation契約

`ActivityInvocation`は次を持つ。

- `invocation_id`
- Foundation `SystemCommand`
- provider非依存な`operation_ref`
- strict JSON objectのbounded `arguments`
- `interruptibility`: interruptible / soft_cancel_only / non_interruptible
- `requested_at`

raw user text、Provider SDK object、具体Plugin API、Body joint、TTS engine値を入れない。`command_id`と`invocation_id`はprocess内で一意とし、同一commandの再admissionを拒否する。

## 4. PreflightとCapability binding

`ExecutionPreflightSnapshot`はcommit/start直前のcurrent stateを一貫して読む。

- current `RevisionVector`
- current `CapabilityDescriptor`
- current `ExecutionPreconditionState`
- `captured_at`

admissionでは次をfail-closedで検証する。

1. command authority、intent kind、identity、deadline。
2. commandが保持する全present revisionとcurrent revisionの一致。
3. required capabilityごとにcurrent available、または明示許可されたdegraded descriptorが存在する。
4. selected capability ID・descriptor revision・requirementをimmutable `CapabilityBinding`へ固定する。
5. precondition ID・subject・predicateがcurrent stateと一致し、current actualがexpectedと一致する。
6. command / invocationの重複がない。

dispatch直前にもcurrent preflightを再取得し、revision、Capability bindingのID/revision/availability、Precondition identity/actualを再検証する。開始時snapshotをそのままcurrentとして再利用しない。Capability不足は`UNSUPPORTED`、Authority/precondition/revision/deadline違反は`REJECTED`、開始前staleは`SUPERSEDED`または`TIMED_OUT`としてtypedに閉じる。

## 5. LifecycleとActual Fact

Foundation `ExecutionResult`のvalidated transitionだけを使う。

```text
REQUESTED
→ ACCEPTED
→ PLANNED? / STARTED
→ OBSERVABLE? / APPLIED?
→ COMPLETED
```

terminalは`REJECTED / UNSUPPORTED / FAILED / CANCELLED / TIMED_OUT / SUPERSEDED`である。Adapter reportは`STARTED`以後の候補milestone、時刻、strict details、typed effect evidenceを返すだけで、Authorityがcurrent snapshotから合法なedgeを適用する。

`effect_refs`は実際に観測・適用されたeffectだけを表し、Foundationのmonotonic規則を継承する。Intent、accepted、planned、startedはeffectを主張しない。Adapterはraw `effect_refs`を指定せず、dispatch identity、選択済みCapability ID/revision、operation、effect種別を持つtyped `ExecutionEffectEvidence`を返す。Authorityはrecordへ固定したdispatch、Capability binding、operationとの一致を検証した証拠からだけ`effect_refs`を導出する。Capability bindingがない実行はeffect evidenceを受理しない。

report確定時にもdeadlineを再検証する。期限後の成功reportは`COMPLETED`にせず`TIMED_OUT`へ閉じる。期限後に新しい外部effectが判明した場合は、currentが`STARTED`か既存`OBSERVABLE` / `APPLIED`かを問わず、検証済み証拠をFoundationの新規effect必須milestone遷移として先に記録し、同じ時刻の`TIMED_OUT`へ遷移してeffect refsを保持する。外部effect後にcontext/goalがstaleになってもeffect refsを消さず、`APPLIED → SUPERSEDED/FAILED/CANCELLED/TIMED_OUT`等の事実系列として保持する。

## 6. Dispatch Port

`ActivityExecutionPort.execute(request, cancellation)`はProvider非依存Protocolである。`ExecutionDispatchRequest`は一意なdispatch identity、accepted snapshot、Invocation、Capability bindingを持つ。Authorityは開始時に同じdispatch identityをrecordへ固定する。

Portは次の`ExecutionAdapterReport`を返す。

- command/invocation/dispatch identity
- `STARTED / OBSERVABLE / APPLIED / COMPLETED / FAILED / CANCELLED / TIMED_OUT`のreport status
- occurred_at
- strict details
- typed effect evidence

report identity不一致、時刻逆行、非法edge、Capability binding・descriptor revision・operationと一致しないeffect証拠はAuthorityが拒否する。空report、runtime型不正、非法report系列もCoordinatorが例外を外へ漏らさず、既発effectを保持したtyped `FAILED`へ閉じる。例外本文・credential・payloadをActual Factやdiagnosticsへコピーせず、closed failure codeへ変換する。

## 7. Cancellationと並行性

- 各invocationは独立taskとして実行し、Core global lockや単一Activity queueを持たない。
- Authority lockは短い同期state transitionだけを保護し、await、Provider callback、Repository I/Oを含めない。
- CoordinatorはcommandごとのAdapter taskを所有し、interruptibleへの明示cancelではCancellationToken更新と`Task.cancel()`をともに行う。
- soft_cancel_only / non_interruptibleは強制cancelせず、取消要求を記録してlate resultを再評価する。
- Coordinatorはadmit直後かつsecond preflightのawait前にcommandごとの取消contextを登録する。cancelがstartより先に確定した場合、startは例外を出さず既存`CANCELLED` recordへ収束し、Adapterを開始しない。
- dispatch前に外側のexecute taskがcancelされた場合もAuthorityへtyped取消を記録し、orphaned `ACCEPTED`を残さない。
- start後からAdapter task登録までにcancelが競合しても、登録済み取消contextをAdapter signalへ引き継ぐ。interruptible taskを登録した時点ですでに取消済みなら直ちにtask cancellationを適用する。
- cancellation後に外部effectが判明した場合もeffectを保持する。
- slow ActivityがInput、Body realtime、current Speech、別Activityをblockしない。
- timeout/backpressure/schedulingは#322 Runtime Kernel契約へ従い、#329が別のglobal schedulerを作らない。

## 8. Read modelとEvent境界

`ActivityExecutionAuthority.snapshot(command_id)`はimmutable current `ActivityExecutionRecord`を返す。recordはInvocation、Capability binding、ExecutionResult、取消要求を保持する。

確定snapshotはAppraisal / Executive / #366 / Character truthfulness向けtyped Eventへ投影可能だが、consumer側のGoal transitionや発話内容を決めない。Memory保存は別Authorityである。

## 9. 検証

- capability missing / degraded policy / descriptor revision change
- precondition actualおよびID・subject・predicate差替え
- source / goal / attention stale before start
- duplicate command / invocation
- success / rejection / unsupported / failure / cancellation / timeout
- second preflight中の明示cancel・外側task cancel、およびstartとAdapter task登録間のcancel競合
- illegal report identity・edge・timestamp・effect拒否
- external effect後staleでもeffect refs保持
- same command競合admissionは高々1件成功
- multi-Activity並行実行中にslow taskがunrelated taskをblockしない
- Goal Storeを直接mutationせず、Execution FactからExecutiveへ戻す
