# V2 System Integration Contracts

Owner Issue: #360
Root: #317
本体・能力別の結合前提: #334 / #341 / #344 / #350 / #346 / #347 / #352 / #358 / #359 / #365（実施する段階に必要な成果と証拠を照合）
任意GUI接続の前提: #351。親#345 / #356は構成責務の参照であり一律の完了待ちにしない。
Related: #347 / #352 / #365 / #396 / #434 / #445
Status: Canonical Supplement / Design Completion Gate

本体の唯一の完成判定は統合本体アーキテクチャを適用する。既存の段階・実サービス・人間による確認の条件は全体完成の条件として保持し、外部機能固有の未達条件を本体の先行完成へ一律に課さない。

## 1. Purpose

#360は、V2のCore / Body / Plugin / Infrastructure / Subsystemsを段階的に結合し、AI Liver ゆらが**継続主体として非直列・degraded-safe・fact-groundedに動作すること**をSystem levelで検証する。

System Integrationは各Moduleのlogicを再実装しない。

```text
Foundation / Runtime
        ↓
Brain Integration
  ├─ Speech runtime / TTS
  ├─ Memory / Persistence
  └─ Goal / Attention / Activity
        ↓ sibling fan-out
Body Integration → Avatar
        ↓
Plugin capabilities
        ↓
Streaming / Game / GUI / Labs
```

責務グラフを巨大な起動時serial pipelineへ変換しない。

---

## 2. System Integration owns / does not own

### #360 owns

- composition topology verification
- startup/degraded composition verification
- cross-domain identity/revision propagation verification
- system-wide cancellation/shutdown verification
- cross-lane latency isolation verification
- staged integration gates
- end-to-end trace/evidence aggregation
- system boundary scans
- final Verification matrix coordination
- defect routing to owner Work

### #360 does not own

- any Domain decision/state Authority
- provider-specific semantic mapping
- subsystem-specific operational logic
- new fallback rules for failed modules
- Character quality judging automatically

---

## 3. System component classes

### Required Core foundation

Minimum process requires:
- Foundation typed contracts
- Runtime Kernel
- Brain minimum cognition
- lifecycle coordinator

### Core-native optional-at-boot service capability

Core semantic responsibilities remain defined even if a concrete external provider is absent.

Examples:
- LLM-backed roles may become unavailable/degraded
- Persistence may be unavailable
- TTS may be unavailable
- Avatar may be unavailable

Optional provider absence must not redefine module ownership.

### External Subsystems

- Avatar
- Streaming
- Game Skill
- GUI/Admin
- Validation Labs
- Development Tooling

Their absence does not invalidate Core identity.

---

## 4. SystemCompositionSnapshot

Integration records the concrete composition under test.

```text
SystemCompositionSnapshot
- composition_id
- git_head
- config_revision
- runtime_epoch
- component_bindings[]
- provider_bindings[]
- subsystem_bindings[]
- character_definition_revision
- created_at
```

Each binding records:
- logical owner/capability
- implementation identity/version
- availability
- generation/revision

Secrets are excluded.

This snapshot is test/operations provenance, not Domain State.

---

## 5. 統合本体の受入れ範囲

[統合本体アーキテクチャ](unified_core_architecture.md)の単一本体を対象に検証する。Minimum / S2 / S3などを別々の製品起動状態として扱わない。検証単位は責務ごとに分けてよいが、本番構成は同じ全Ownerと同じ起動・終了境界を使用する。

| 検証対象 | 観測する事実 |
| --- | --- |
| 実行基盤 | 並行性、取消、優先度、backpressure、停止後の未回収タスクなし |
| 認知・自律判断 | 入力と内部契機、意味・主観評価・Attention・Executive・Goal・Activityの連動 |
| Speech | 意味計画、人物らしい表現、実発話の要求と提示事実 |
| Body | 内部意図と実際の継続的な身体挙動の独立性 |
| Memory | 保存、復元、現在世代、出典、再起動の整合 |
| Plugin / Subsystems | 任意能力0件・1件・複数件で本体判断を変質させない |
| Human Verification | 実LLM、実音声、自律活動、必要な実行品質 |

未配備の外部提供先と本体の必須Ownerを区別する。未配備Providerを模擬成果で置き換えて実サービスの成功と主張しない。

---

## 6. Startup topology

Startup is dependency-aware but not one long blocking readiness barrier for every optional service.

Logical sequence:

```text
load static configuration / Character Definition
→ initialize Core stores/runtime
→ establish all mandatory Core/Brain owners
→ publish typed availability of Providers/Plugins/Subsystems
→ admit normal work only after the unified Core gate is ready
```

Optional provider/subsystem initialization may continue asynchronously.

Rules:
- TTS unavailable does not block text cognition.
- Avatar unavailable does not block Body Core.
- DB unavailable does not block ephemeral safe Core boot.
- Streaming/Game absent does not block normal operation.
- Plugin 0 is valid.
- unavailable LLM-required semantic path fails typed; no invented result.

---

## 7. Availability propagation

Availability is provider/module owned and projected as typed state.

System Integration verifies:
- unavailable does not become successful fact
- recovery changes appropriate descriptor/generation/revision
- old in-flight results cannot cross reconnect generation fences
- repeated failures do not cause log/queue storms
- one provider failure does not stop unrelated provider/lane

---

## 8. End-to-end interaction lineage

A user interaction may have correlation across multiple independent works.

```text
External Event
→ Meaning
→ Appraisal
→ Attention eligibility
→ Executive Decision
   ├─ Goal/Activity
   ├─ Speech
   └─ Body
```

System trace must retain:
- source event IDs
- decision ID
- source_context_revision
- goal_revision
- attention_revision
- Activity execution IDs
- Speech candidate/presentation IDs
- Body intent/plan/execution refs

No requirement that every branch exists for every decision.

---

## 9. Speech System path

Full speech Verification:

```text
#328 SpeechIntent
→ #362 SpeechSemanticPlan
→ #330 CharacterUtterance
   ├─ #363 Semantic Verification
   └─ #331 SpeechPerformancePlan
→ #358 safe audio preparation when policy allows
→ #348 live revalidation / Presentation commit
→ actual playback/report
→ #329 execution fact evidence where applicable
→ actual timing → #340 viseme
```

System acceptance:
- verifier-required speech never externally presents before acceptance.
- Performance/TTS safe work may overlap verifier.
- Speech A playback does not block Speech B cognition/preparation.
- stale queued speech never presents.
- TTS artifact ≠ spoken fact.
- failed/interrupted-after-start preserves partial effect.

Formal #434 Human Character quality may be resumed only after this actual Presentation path exists.

---

## 10. Body System path

```text
Executive BODY intent
→ #338 Plan
→ #339 physical solve/controller
+ #337 expression
+ #340 realtime overlays
→ BodyState / BodyPoseFrame
→ #346 Avatar
```

System acceptance:
- Character and Body planning sibling fan-out.
- Planner delay does not stop current trajectory/gaze/blink/breath/viseme.
- no Home reset.
- true 3D canonical directions/composite motion/jump.
- renderer slowdown/unavailable does not stop BodyState.
- 2D renderer limitation is Adapter degradation, not Core capability deletion.

---

## 11. Memory / continuity System path

```text
trusted historical results
→ #364 Reflection
→ #332 Store
→ #359 persistence
→ later bounded retrieval
```

Verify:
- Reflection background/nonblocking.
- LLM proposal support gate.
- contradiction preserved.
- vector similarity not truth authority.
- actual result evidence required for actual-history memory.
- restart restores only owner-declared restart-safe state.
- old Emotion/Attention/queued Speech/current Body pose/in-flight Activity not blindly restored.
- Goal/Commitment uses owner rehydration contract.

---

## 12. Plugin System path

Verify both:

### Zero plugin

Core normal operation with empty capabilities.

### One plugin

```text
Registry
→ CapabilityDescriptor
→ Executive/Planner view
→ #329 preflight
→ Plugin execution
→ effect evidence
→ #329 Actual Fact
```

Permission revoke/lifecycle stop/generation races must preserve already-applied effects and reject stale new work.

---

## 13. Streaming System path

```text
NL request
→ #326 semantic meaning
→ Executive
→ generic Activity/Capability
→ Streaming Subsystem provider operation
→ report / external observation
→ Actual Fact/Appraisal/Attention
```

Verify:
- no provider-specific Core classes/IDs/SDK.
- no literal NL matcher outside #326.
- provider observation vs user report provenance.
- start intent/Character claim not `LIVE` fact.
- comments bounded/aggregated.
- reconnect/API delay does not block Core.
- stream end does not shut down Core.

---

## 14. Game + Streaming simultaneous scenario

Required system stress scenario:

```text
Game Skill foreground realtime loop
+ Streaming secondary comment monitor
+ active Body realtime
+ possible current Speech presentation
+ background Reflection
```

Then direct user interaction arrives.

Expected:
- Game frame loop continues unless Core explicitly pauses/quits.
- Streaming ingestion continues bounded.
- #333 may prioritize direct interaction.
- Executive handles trigger without waiting for TTS/current playback completion.
- Body continues realtime.
- background Reflection yields/deprioritizes without starving foreground.

---

## 15. Natural-language semantic generalization

System Verification confirms #326 remains the only open-ended NL Authority.

Test categories include Streaming request/state reports and general interaction.

Paraphrases vary:
- vocabulary
- word order
- politeness
- colloquial form
- ellipsis
- contextual references

Deleting/changing a single literal fixture must not disable semantic category behavior.

Boundary scan forbids finite keyword/regex/substring semantic fallback in Executive/Activity/Streaming/Game etc.

---

## 16. Cross-lane latency isolation

Inject deliberate delays:

- Input Meaning 10s
- Deep Appraisal 10s
- Planner 10s
- Verifier 10s
- Reflection 20s
- Body Planner 20s
- TTS 10s
- Streaming provider 10s
- slow Avatar renderer

For each, specify unrelated lanes that must continue.

Evidence uses timestamped intervals/heartbeats, not subjective observation only.

Pass criteria must demonstrate overlap and bounded queue behavior.

---

## 17. Foreground starvation gate

Under simultaneous background load:
- multiple Reflection requests
- autonomous speech preparation
- Streaming aggregation
- Game observations

inject direct user input.

Verify foreground:
- admitted within bound
- provider work receives priority policy
- background queued work coalesces/cancels if necessary
- no unbounded LLM/task growth

Exact latency SLO values may be environment-specific, but bounded/non-starved behavior is required and measured p50/p95/p99.

---

## 18. Actual Fact invariant

Across all System scenarios:

```text
intent != plan != prepared candidate != external effect != observed result
```

Verify:
- speech generated ≠ spoken
- Body plan ≠ physically applied
- Plugin request ≠ external operation success
- Streaming start intent ≠ LIVE
- Game selected action ≠ applied action
- user report ≠ provider-confirmed observation

Actual Fact owner consumes trusted result/effect evidence only.

---

## 19. Revision / generation fences

System Integration verifies owner-specific freshness jointly:
- source_context_revision
- goal_revision
- attention_revision
- character definition revision
- capability descriptor revision
- plugin/subsystem/provider generation
- Body model identity
- persistence schema/payload versions

No universal `all revisions must equal` rule.

Only declared dependencies invalidate a work item.

---

## 20. Restart / rehydration

System restart scenario:

1. run and create eligible persistent state.
2. persist via #359.
3. simulate clean/unclean termination.
4. new runtime epoch.
5. load `RehydrationCandidate`.
6. owner validates/apply only restart-safe state.

Verify operational/in-flight state from prior epoch is not automatically resumed.

Memory historical data remains historical evidence.

---

## 21. Graceful shutdown

Use #350 sequence.

System acceptance:
- stop external admission
- stop new speech candidates
- cancel/supersede queued work
- bounded handling of interruptible/non-interruptible work
- stop frame/event producers
- close Subsystems/Providers in dependency-safe order
- best-effort persistence without blocking resource close forever
- stop retry loops
- pending task count = 0
- repeated stop idempotent

Streaming ending is not equivalent to System shutdown.

---

## 22. System trace

```text
SystemVerificationTrace
- verification_run_id
- composition_snapshot
- scenario_id
- timeline_events[]
- work_intervals[]
- revision_conflicts[]
- availability_transitions[]
- actual_effect_observations[]
- metrics
- machine_gate
- human_gate_refs[]
```

This is Verification evidence only.

---

## 23. Metrics

Minimum:
- Role queue wait/provider latency/token/cost where available
- end-to-end interaction p50/p95/p99
- user input→Meaning
- user input→Attention eligible
- user input→Executive
- user input→speech preparation/presentation
- playback中next generation start
- concurrent in-flight
- stale/cancel/supersede
- foreground starvation metrics
- Body frame interval/jitter
- Game frame stability/deadline misses
- Streaming ingress/aggregation/drop
- provider request/reconnect latency
- Memory Reflection/persistence metrics

---

## 24. Human Verification matrix

GUIの操作性は任意GUI側の確認であり、本体完成条件には含めない。可聴音声、身体、実ゲーム、配信等で必要な証拠は維持する。GUIの不在と、これらの証拠が未取得であることを混同しない。

Machine contract tests precede Human Verification.

Human-required examples:
- actual LLM conversational behavior
- #434 Character naturalness/fidelity in full speech context
- actual TTS/performance quality
- Body natural motion / coordination
- Stick/Live2D/Avatar visuals
- real Streaming lifecycle/comments
- real Game operation
- GUI usability

Human PASS cannot be inferred solely from automated schema/timing PASS.

---

## 25. Boundary scans

Automated/static scans include:
- Core imports no YouTube/OBS concrete SDK/type.
- Core imports no renderer/Live2D concrete type.
- Provider SDK object absent from Domain DTO.
- no finite raw-NL matcher outside approved #326 internals/contracts.
- Development Tooling not imported by production Core.
- GUI/Lab does not own direct Domain mutation.
- Character/Body/Skill AI do not own Executive Goal.

Findings route to owning Work.

---

## 26. Defect ownership

Classify failure:

```text
MODULE_CONTRACT_DEFECT
MODULE_IMPLEMENTATION_DEFECT
ADJACENT_CONTRACT_MISMATCH
SYSTEM_WIRING_DEFECT
PROVIDER_OR_ENVIRONMENT_DEFECT
VALIDATION_HARNESS_DEFECT
HUMAN_QUALITY_DEFECT
```

Do not patch #360 with special-case logic to mask module defects.

An independent defect is filed/returned to owner Issue and System scenario re-run after fix.

---

## 27. System release gate

System PASS requires:
- all required Unit/Adjacent/Integration machine gates
- no unresolved blocking boundary defect
- actual required provider/system Verification
- Human Verification for subjective/external surfaces
- current-head evidence/provenance
- no stale review/evidence acceptance

#360 completion does not by itself change branch/release policy; #207/project management rules remain authority.

---

## 28. #445 Gate

System Integration implementation and final Verification remain frozen until #445 D1-D9 and final user Design Completion confirmation PASS.


## 29. 本体優先の段階結合と最終確認（2026-09-07）

本体を先行完成させる。従来の段階ごとの成果・未完了条件を保持したまま、配信・ゲーム技能・具体プラグイン・GUIと、それらに固有の実サービス・実機・画面品質の証拠を後続へ分ける。外部機能が未接続、未実装、レビュー待ちでも本体の製造を止めない。

本体側の完了判定には次を必要とする。

1. 入力と権威ある現在文脈から、意味解析・評価・状態・注意・判断への具体接続。
2. 判断から目標・確定計画・汎用活動を進行し、結果を次の評価・判断へ戻す接続。計画全体への明示的承認範囲を守り、検証基盤で判断を補作しない。
3. 発話意味・人物としての言語化・意味検証・演技・実音声・実提示、および提示中の次候補準備と割込み。
4. 本体の身体状態・実時間処理の継続、記憶保存・検索・振り返り、所有者が許可する状態の永続化・復元。
5. 模擬能力提供先による成功・利用不可・失敗・取消・結果返却。配信・ゲーム固有の固定判断を本体へ追加しない。
6. 遅い処理中の無関係な入力・認知・発話・身体・背景処理の並行継続。正常停止時の所有タスク・資源回収と、許可された状態だけの再起動復元。
7. 状況に由来する文脈、人物・方針のリビジョンやモデルのバージョンの来歴を備える実発話について、#434の人間による自然さ・ゆららしさの確認。

最小起動、単体合格、模擬提供先の成功を、上記全体の合格や後続の実サービス品質へ昇格しない。本体の先行完成と後続を含む全体完成を別に判定する。#586の性能試験・改善は本体実装完了後の別工程であり、今回は着手しない。

## 30. #624 能力提供0件・模擬提供1件の自動結合検証

`tests/system_integration/test_system_plugin.py`は既存の`build_minimum_core`と`CoreCognitionConfiguration` / `CoreExecutionConfiguration`を使用する。RegistryとPluginCapabilityPreflightPort / PluginActivityExecutionPortを同じ構成へ注入し、別の状態Ownerや特定サービスへの固定意思を作らない。模擬提供先だけを登録し、実サービスへ接続しない。

能力提供0件では、空Registryのまま通常の内部入力からAppraisal・Executiveへ到達する。能力提供1件では、公開RegistryからActivityBindingへ投影した確定判断を配送し、実行要求・報告・Activityの現在の終端事実・入力文脈・後続認知を同じtraceで照合する。入口が確定判断であるため、先行する実LLMの能力選択をこの試験で実行したとは扱わない。

正常終了、実行前の権限失効、効果未確定のtimeout、取消と再取消、効果報告後の権限失効を確認する。実行前に根拠が失効した場合はFinalizationErrorとして拒否され、提供先呼出し0件となる。実行後の権限失効は既存効果を消さず、Activityの終端事実はAppraisalの入力へ戻る。一方、失効したBindingを含む後続Executiveは既存Ownerの現在性検査で拒否される。これを後続判断の成功とは報告しない。

試験は本番の構成処理・Owner・配送・起動停止を使用する自動結合検証であり、配備された製品の実動作やHumanの受入を代替しない。2026-09-22のユーザー指示に従い、実音声を含む実動作の検証はHumanが所有し、ChatGPT/Codexは実施しない。模擬提供先・模擬LLMの試験成功を実サービスや意味品質の成功へ昇格しない。

## 31. 通常入力・内部契機から判断までのSystem Acceptance（#620）

#620は採用済みproduction compositionとcurrent production configurationを使用し、#561・#569の起動構成、#611の通常認知、#615の非直列性、#616の検証入口をSystem段階で対応付ける。最小起動だけ、またはValidation Lab単独のPASSをSystem PASSとしない。同じ起動構成・実行世代について、登録role、policy、character definition、HEAD、入力と公開終端・traceを照合する。

### 31.1. 受入対応

| シナリオ | Systemから確認する既存Ownerの成果 |
| --- | --- |
| A 外部入力 | 正規Input AdmissionのUSER入力を採用済みMeaningからAppraisal・Attention・Executiveへ配送する。raw text再解釈・fallbackを作らず、Decisionと元イベントを対応付ける |
| B 内部契機 | SUBSYSTEM / LIFECYCLE / TIMER等の内部契機は架空のInput Meaning成功を生成せず、内部入力からAppraisal・Attention・Executiveへ進む。USER由来と混同しない |
| C 型付き失敗 | provider/moduleの利用不可・失敗を公開結果とtraceに保持し、不正な後続Executiveや成功fallbackを生成しない。無関係なtraceは継続する |
| D 現在性 | 外部提供先を待機させた間に依存するrevisionを正規Ownerで更新し、旧結果の拒否とDecision・後続effect非生成を確認する。現在contextへの付替えは禁止する |
| E 取消・置換 | 待機中trace Aだけを取消またはsupersedeし、System consumerが非成功終端を回収する。別trace Bの継続とsource非流用を確認する |
| F 非直列性 | Aの遅い認知を解放する前にBのforeground受付・Meaningを進める。Event / Futureで同期し、global lockや性能SLO試験を追加しない |
| G 停止 | 認知中のSystem stopで新規受付を閉じ、公開終端を回収し、対象Brainのowned task・queue・in-flightを0へ収束させる。反復stopと試験task回収を確認する |

Meaning・Appraisal・Attention・Executiveのsource event / root_trigger / trigger / context・Goal・Attention revisionはそれぞれのOwnerが宣言した由来に対応付ける。一律に全revisionを等置しない。stale・superseded・cancelledは後続判断の成功根拠にしない。

### 31.2. Validation証拠と責務境界

#616のnormal_cognition_target / ValidationRunnerはINTEGRATEDの公開契約を維持する。対応できる通常認知の入力・出力・trace・provenanceは既存証拠形式を再利用し、System構成の観測と照合する。複数traceやSystem停止の証拠はSystem試験から既存production outputを観測する。SYSTEM_SLICEへ形式だけ付け替えず、ValidationにMeaning・Decisionを補作させない。

新しいMeaning / Appraisal / Attention / Executive / Goal / Activity Owner、system-global lock、試験専用production semantic pathは追加しない。独立欠陥は§26で分類し、該当Ownerへ戻す。System配線・対象harnessの欠陥だけを#620で修正し、別Ownerの不具合を局所回避しない。

提供先を置換した自動試験は実LLM・実音声・実サービス・Human Verificationではない。Human実動作はNOT_RUN / UNRATEDを維持する。#621〜#625、#434、#586、GUI・Game・Streamingの受入れへ拡大しない。

## 統合構成の正式起動

`python -m app` は[統合本体アーキテクチャ](unified_core_architecture.md)の全必須Ownerを同一runに組み立てる。旧S2専用CLIと最小Coreは廃止し、本体の全機能を接続して検証する。Speech構成とProviderの接続は正規Ownerの方針を保ち、未構成・availability不足を成功へ読み替えない。
