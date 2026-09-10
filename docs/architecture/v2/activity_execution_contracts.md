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
- `primary_binding: CapabilityBinding | None`（#651で追加する契約。詳細は第4.1節）

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
3. required capabilityごとにcurrent available、または明示許可されたdegraded descriptorが存在する。exact primary指定時は第4.1節の固定identityだけを照合し、残る要件だけを従来どおり解決する。
4. selected capability ID・descriptor revision・requirementをimmutable `CapabilityBinding`へ固定する。
5. precondition ID・subject・predicateがcurrent stateと一致し、current actualがexpectedと一致する。
6. command / invocationの重複がない。

dispatch直前にもcurrent preflightを再取得し、revision、Capability bindingのID/revision/availability、Precondition identity/actualを再検証する。開始時snapshotをそのままcurrentとして再利用しない。Capability不足は`UNSUPPORTED`、Authority/precondition/revision/deadline違反は`REJECTED`、開始前staleは`SUPERSEDED`または`TIMED_OUT`としてtypedに閉じる。

### 4.1. 確定primary Capabilityの保持（#651）

本節は#651の契約修正であり、製品実装・試験は後続の同じlineageで行う。#649が確定したCapabilityを#329が別Capabilityへ再選択できる公開要求の欠落を解消する。#329・#649の既存採用成果を取り消すものではない。

`CapabilityRequirement`は「何の能力が必要か」、既存の`CapabilityBinding`は「使用するCapability ID・descriptor revision」を表す。新しい並行型を作らず、#329の`ActivityInvocation.primary_binding`に既存の不変`CapabilityBinding(requirement, capability_id, descriptor_revision)`を保持する。Foundationの`CapabilityRequirement`へ具体identityを追加しない。Provider SDK・Plugin Registry固有型を要求へ入れない。

#649 `direct_invocation()`は、確定判断の正本要件集合から`requirement.capability_type == binding.activity_type`かつ`requirement.operation == binding.operation_ref`を満たすprimaryをexactly oneで取得する。0件・2件以上は投影を拒否し、先頭を選ばない。#630の同一`(capability_type, operation)`重複禁止を維持し、`allow_degraded`を含む元の要件を変更せず、#649の`capability_id / capability_revision`と組にして`primary_binding`へ投影する。

要求自体も、primaryの要件が`command.required_capabilities`に一意に存在し、同じtype / operationの別要件がなく、primaryのoperationが`invocation.operation_ref`と一致することを検査する。不整合は不正なtyped要求として構築・投影時に拒否し、実行しない。#649由来のDirect投影およびPlanのscope gateではprimary欠落を拒否する。#649を通らない既存generic要求に限り`primary_binding=None`を許し、その場合の既存選択規則を維持する。exact指定の拒否後にNoneへ落とす互換処理は禁止する。

#### 初回admission

primaryのcurrent descriptorは指定IDだけで取得し、次の順序で照合する。下表はprimary単体の失敗分類である。

| 現在値と確定identityの関係 | 終端status / details.code |
| --- | --- |
| exact IDが存在しない | `UNSUPPORTED / capability_unavailable` |
| exact IDは存在するがdescriptor revisionが異なる | `SUPERSEDED / capability_changed` |
| ID・revisionは一致するがtype・operation・availability・degraded許可を含む`descriptor.satisfies(primary.requirement)`が偽 | `UNSUPPORTED / capability_unavailable` |
| ID・revision・要件がすべて一致 | 確定済みprimaryをそのままbinding集合へ保持し、残る受付検査へ進む |

最後から2行目は、初回受付で要件を満たす能力を利用できないという既存の`capability_unavailable`分類に従う。同IDのrevision不一致を、候補検索の不成立へ読み替えない。別の利用可能Capabilityがあってもfallbackしない。例えば`capability-a@3`を確定し、currentに`capability-0@8`と`capability-a@3`が存在する場合もprimaryは必ず`capability-a@3`である。

primaryの照合後、auxiliaryには既存のcurrent deterministic selectionを適用する。各`command.required_capabilities`へ1つずつbindingを対応させ、要件の削除・primaryの全要件への強制を行わない。auxiliary不足は既存`UNSUPPORTED / capability_unavailable`とし、primaryの成功だけで受付を成功にしない。primaryの失敗がある場合は上表で閉じ、それ以外のauthority・重複・期限・revision・precondition検査とauxiliaryに関する既存の拒否規則は維持する。

#### 開始直前の再検査と事実の保持

second preflightではadmissionで固定したprimary・auxiliaryのbinding集合を再選択せず検証する。currentの同じID・descriptor revision・要件充足を照合し、primaryのoperationと要求のoperationの一致も維持する。固定済みIDの消失、revision変更、availability / degraded許可 / type / operationの不一致は既存`SUPERSEDED / capability_changed`として拒否する。期限・文脈・前提条件など他の失敗分類は従来どおりであり、Capabilityの変更で救済しない。

primaryは要求の不変内容として直列化し、`ExecutionDispatchRequest`・`ActivityExecutionRecord`にも同じ要求とbindingを保持する。実行時のbinding集合でprimaryに対応する要素は要求のexact bindingと一致しなければならない。拒否された要求を実行済みと扱わず、拒否前にProviderを呼ばない。effect evidenceのCapability ID・descriptor revision・operation照合、取消、終端lifecycle、effect uncertaintyの意味は変更しない。

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

report identity不一致、時刻逆行、非法edge、Capability binding・descriptor revision・operationと一致しないeffect証拠はAuthorityが拒否する。空report、runtime型不正、非法report系列もCoordinatorが例外を外へ漏らさず、既発effectを保持したtyped `FAILED`へ閉じる。提供先の返却後に報告系列が`OBSERVABLE / APPLIED`等の非終端で終わっている場合も報告契約違反として閉じ、確認済みeffectを保持し、未確定性を`UNKNOWN`として記録する。提供先が終了した実行を非終端のまま残さない。例外本文・credential・payloadをActual Factやdiagnosticsへコピーせず、closed failure codeへ変換する。

## 7. 取消と並行性

提供先の処理開始後は、呼出し側が繰り返し取り消されても、所有する提供先タスクの終了と実際の結果の回収を完了する。取消要求は提供先へ通知し、強制取消可能な処理への`Task.cancel()`は高々1回として終了処理中の再取消を防ぐ。強制取消不可の処理は終了まで保持し、返された確定効果を取消結果へ付け替えない。呼出し側の取消を受けた`execute()`は既存契約どおり型付き実行記録を返す。

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


## 計画から活動への公開接続（#334）

計画に由来する命令も既存の事前確認と実行事実の境界を通る。計画全体への承認範囲は`plan_execution_approval_contracts.md`で定義し、未提供能力・失敗・未確認効果を成功へ変更しない。

計画由来の活動要求は`ActivityInvocation.target_ref`に承認済みの対象参照を保持する。操作引数とは独立に不変の要求内容として直列化し、提供先へ伝達する。既存の対象を持たない単独活動では未指定を許す。

## #649 活動bindingの上流境界

`ActivityBindingAuthority`は意識的な活動選択や実行事実を所有しない。信頼済み構成が操作・対象・Capability・引数名と事実参照の対応を明示する。`direct_invocation()`は確定判断の検証済みbindingを読取り、既存`to_system_command()`経由の命令とともに`ActivityInvocation`へ機械投影する。#329のpreflight、取消、効果・実行事実の意味は維持する。#612の実行・還流配線は別途未実装。

`ArgumentSourceOwnerPort`は実値Owner自身のparticipantとboundedなcurrent factsを同一読取で公開する。1正規Ownerが複数factを持ち、単一tokenがそれらのcurrentnessを表す。既存Ownerは自身の更新lockを公開境界へ使い、別のcopy/shadow Ownerへ値を移さない。`ArgumentSourceOwner`は自身が実値Authorityである場合の集合実装であり、各factのowner identity・strict revisionを検査し、同一revisionの内容変更を拒否する。値はstrict JSONで不変化する。`BindingInputPublicationOwner`は入力schema自身のOwnerであり、実値の集約枠ではない。`ArgumentSourceRelation`は引数名からexact事実参照への対応であり、値の変換・切出し・既定値を持たない。

bindingは一identity一Owner・一公開値とし、履歴を蓄積しない。引数relation参照には既存Executive `max_refs_per_intent`、Ownerのcurrent fact集合・publication件数には`max_fact_refs`、引数・fact集合・全公開payloadには`max_fact_payload_json_bytes`を適用する。これらの構造・JSON容量上限は#632のdistinct participant上限16とは別制約であり、同数の独立Ownerが確定可能という意味ではない。別bindingの更新は独立participantを使い、未宣言の依存を全域失効させない。closeはparticipantを失効させ、旧instanceのtokenを再利用しない。

失敗・同値更新も既存participantの世代を失効させる。binding更新が拒否された場合、旧captureはstaleのままとし、出典tokenが変化していなければ現在のbinding tokenを再取得できる。出典変更を新しいbinding tokenだけで救済しない。再開の機械投影には既存Activity Ownerを明示し、非終端の元要求を取得する。操作・対象・引数・権限の照合は既存PlanExecutionScope / Ownerの検査を維持する。

### binding publicationの最終確定

`ActivityBindingAuthority.publish()`も既存`AuthorityFinalizationFence`の登録済み同期操作で確定する。operation/schema/source Ownerから同時読取した値と正規token、および確定先の期待tokenを渡す。使用するfactを持つ各Ownerのtokenを省略せず、複数factでも同じOwnerのtokenは重複正規化できる。総participantが17以上なら`INVALID_LOCK_CONFIGURATION`でpublicationを更新しない。sourceをコピーして集約する別participant、内部の未宣言lock取得、上限拡大、nested Fenceを設けない。

失敗・no-opを含むpublish進入で旧binding tokenを失効させる。失敗時は旧publicationの値・元source tokenを保持し、新sourceへ付け替えない。fresh captureによる自分のtoken再取得は、保持した元sourceが現在も有効な場合だけ許す。binding単独の確定が16以内でも、後続Executive / Plan Authorizationのevidence等を加えた総数が17以上なら、その後続確定は正規の容量拒否になる。
