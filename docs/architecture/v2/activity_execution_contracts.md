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

terminalは`REJECTED / UNSUPPORTED / FAILED / CANCELLED / TIMED_OUT / SUPERSEDED`である。Adapter reportは`STARTED`以後の候補milestone、時刻、strict details、effect refsを返すだけで、Authorityがcurrent snapshotから合法なedgeを適用する。

`effect_refs`は実際に観測・適用されたeffectだけを表し、Foundationのmonotonic規則を継承する。Intent、accepted、planned、startedはeffectを主張しない。外部effect後にcontext/goalがstaleになってもeffect refsを消さず、`APPLIED → SUPERSEDED/FAILED/CANCELLED`等の事実系列として保持する。

## 6. Dispatch Port

`ActivityExecutionPort.execute(request, cancellation)`はProvider非依存Protocolである。`ExecutionDispatchRequest`はaccepted snapshot、Invocation、Capability bindingを持つ。

Portは次の`ExecutionAdapterReport`を返す。

- command/invocation identity
- `STARTED / OBSERVABLE / APPLIED / COMPLETED / FAILED / CANCELLED / TIMED_OUT`のreport status
- occurred_at
- strict details
- effect refs

report identity不一致、時刻逆行、非法edge、effect捏造はAuthorityが拒否する。例外本文・credential・payloadをActual Factやdiagnosticsへコピーせず、closed failure codeへ変換する。

## 7. Cancellationと並行性

- 各invocationは独立taskとして実行し、Core global lockや単一Activity queueを持たない。
- Authority lockは短い同期state transitionだけを保護し、await、Provider callback、Repository I/Oを含めない。
- interruptibleはCancellationTokenとtask cancellationを利用可能。
- soft_cancel_only / non_interruptibleは強制cancelせず、取消要求を記録してlate resultを再評価する。
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
- illegal report identity・edge・timestamp・effect拒否
- external effect後staleでもeffect refs保持
- same command競合admissionは高々1件成功
- multi-Activity並行実行中にslow taskがunrelated taskをblockしない
- Goal Storeを直接mutationせず、Execution FactからExecutiveへ戻す
