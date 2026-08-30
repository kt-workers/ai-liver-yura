# V2 Brain Integration 実装契約

Owner: #334  
Related: `brain_integration_contracts.md`, `runtime_kernel_contracts.md`, `snapshot_consistency_contracts.md`  
Status: Canonical implementation mapping

## 1. 目的

#334はBrain各Moduleの意味・状態・判断を再実装せず、既存ownerをRuntime Kernel上で非直列に結合する。

実装は次だけを所有する。

- Module Port登録
- Brain workからRuntime laneへの明示mapping
- structural prerequisiteの順序Gate
- owner freshness判定の委譲
- cancellation / supersede propagation
- read-only integration trace
- bounded queue / concurrency policyのComposition
- optional Module未登録時の明示的rejection

意味的fallback、revisionの意味解釈、Goal/Decision/Speech/Memoryの生成はowner Moduleだけが行う。

## 2. Runtime topology

```text
BrainIntegrationRuntime
  |
  +-- RuntimeCoordinator
  |    +-- foreground_interaction
  |    +-- cognitive_normal
  |    +-- speech_preparation
  |    +-- background_reflection
  |
  +-- BrainModulePort[INPUT_MEANING]
  +-- BrainModulePort[APPRAISAL]
  +-- ...
  +-- BrainModulePort[REFLECTION]
```

`BrainIntegrationRuntime`は単一の巨大Cognitive Loopを作らない。各laneは`RuntimeCoordinator`の独立workerとして動作し、無関係なlane間でglobal async lockを共有しない。

## 3. Versioned runtime policy

```text
BrainIntegrationRuntimePolicy
- policy_id
- policy_revision
- scheduler_policy: RuntimeSchedulerPolicy
- lane_policies: exactly one RuntimeLanePolicy per BrainIntegrationLane
```

Rules:

- 4つの`BrainIntegrationLane`をexactly once定義する。
- queue capacity、max in-flight、cancellation grace、error isolation、priority burstはRuntime Policyから明示する。
- #334にhidden numeric defaultを持たせない。
- `QueuePolicy.COALESCE`は#334で禁止する。異なるowner payloadをどう意味的に統合するかを#334が推測できないためである。必要なcoalesceはowner Moduleまたはowner専用Adapterで定義する。
- policy missing/invalidは起動前にfail-closedする。

## 4. Brain work

```text
BrainIntegrationWork
- work_id
- module
- lane
- envelope: BrainWorkEnvelope
- payload: opaque owner payload
- prerequisite_work_ids
- queue_key?
- deadline_at?
- interruptible
```

#334は`payload`のfieldや値でrouting/decisionを行わない。

`BrainWorkEnvelope`のsource/goal/attention revisionはRuntimeの`RevisionVector`へtransportするが、fresh/staleの意味判定には使用しない。

## 5. Owner Port

```text
BrainModulePort
- is_fresh(work) -> bool
- execute(work, CancellationToken) -> object
```

- `is_fresh`は各ownerのrevision/precondition contractを実装する境界。
- #334は「revisionが変わったら全work stale」のような共通意味規則を持たない。
- Runtime Kernelは実行前後にowner freshnessを再確認する。
- staleならowner `execute`結果をDomain commitへ昇格せず`STALE`として記録する。

## 6. Structural prerequisite

Goal確定後だけPlannerを開始する等、意味ではなく構造として確定している順序は`prerequisite_work_ids`で表す。

- prerequisiteは`COMPLETED`だけを満了とする。
- 未完了なら`PREREQUISITE_PENDING`を返し、hidden待機queueへ入れない。
- callerはowner state/revisionを再取得したうえでnew admissionを行う。
- prerequisiteを持たないsibling workは同時進行できる。
- これによりGoal→Plannerの必要順序だけを守り、Speech等の無関係workを停止しない。

## 7. Cancellation / supersede

- `cancel(work_id, reason)`はRuntime Kernelへそのまま委譲する。
- `supersede(work_id, reason)`はRuntime cancellationを要求し、public integration outcomeを`SUPERSEDED`へ固定する。
- queue replacementにより旧workが押し出された場合も、旧workを`SUPERSEDED`としてtraceへ残す。
- cancel/supersede済み結果をsuccessへ戻さない。

## 8. Runtime disposition mapping

Runtimeの終了事実を次のようにlosslessにBrain traceへ写す。

| Runtime | Brain |
| --- | --- |
| COMPLETED | COMPLETED |
| FAILED | FAILED |
| CANCELLED | CANCELLED |
| TIMED_OUT | TIMED_OUT |
| STALE | STALE |
| SUPERSEDED | SUPERSEDED |
| REJECTED | REJECTED |

このため`BrainWorkStatus`と`BrainIntegrationTerminalOutcome`は`TIMED_OUT` / `STALE`を明示的に持つ。

## 9. Trace Authority

`BrainIntegrationTrace`は観測証拠であり、各Moduleの正本状態を書き換えない。

#334が直接記録できるもの:

- work interval / lane / terminal status
- source/goal/attention revision transport値
- ownerが通知した`BrainRevisionEvent`
- ownerが確定済みとして渡したdecision / goal transition / activity / speech candidate identity

#334自身がdecision idやrevisionを生成しない。

`finalize_trace`は、そのtraceに登録されたworkがすべてterminalになった後だけ許可する。

## 10. Degradation

minimum text cognitionに不要なModuleを未登録にできる。

- 未登録Module向けworkは暗黙fallbackせず`REJECTED / UNREGISTERED_MODULE`。
- 登録済みModuleや別laneの処理は継続する。
- TTS / Avatar / Streaming / Game / persistence不在をBrain全停止へ変換しない。

## 11. Required verification

Unit / Adjacent:

- 4 lane policy coverageとCOALESCE拒否
- slow background reflection中もdirect-user foregroundが完了
- Goal prerequisite待ち中も無関係Speechが完了
- prerequisite完了後にPlannerを再admit可能
- owner freshness=falseでowner executeを呼ばずSTALE
- running workのsupersedeがCANCELLEDへ情報落ちしない
- deadline expirationをTIMED_OUTとしてtrace
- optional Module未登録をtrace-visible REJECTED
- 未終了workがあるtraceのfinalize拒否
- owner-confirmed revision/decision/goal/activity/speech identityだけをtraceへ記録

System Integrationでは各ownerのreal/fake Port wiringを別Gateで確認する。#334 Unitでowner semanticsをmock実装して再定義しない。
