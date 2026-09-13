# V2 Speech Runtime / Presentation Contracts

Owner Issue: #348
Parent: #325
Upstream: #322, #328, #333, #362, #330, #363, #331
Downstream: #358, #329, #340
Related:
- `docs/architecture/v2/speech_pipeline_architecture.md`
- `docs/architecture/v2/concurrency_architecture.md`
- `docs/architecture/v2/speech_performance_contracts.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

#348は、Speechの各責務を分離したまま、**Preparation / semantic acceptance / audio preparation / queue / revalidation / Presentation**を非直列Runtimeとして調停する。

```text
Committed Executive Speech Intent
        ↓
#362 Speech Semantics
        ↓
#330 Character Language
        ├────────→ #363 Semantic Verification
        └────────→ #331 Speech Performance
                        ↓
                 #358 optional/speculative TTS
        ↓ readiness convergence
PreparedSpeechCandidate
        ↓
queue / revalidation / Presentation commit
        ↓
Presentation Adapter
        ↓
SpeechPresentationReport
        ↓
#329 Actual Execution Fact normalization
```

この図はAuthority/Data dependencyであり、固定serial await列ではない。

---

## 2. Ownership

#348 owns:
- one Speech candidateのPreparation orchestration
- candidate lifecycle
- verifier requirement policyのclosed decision
- semantic repair / bounded regeneration orchestration
- component readiness aggregation
- speculative artifact discard
- bounded prepared queue / priority arbitration
- pre-presentation revalidation
- Presentation commit decision
- interrupt / supersede / cancellation policy
- Presentation operational lifecycle / reports
- speech runtime observability

#348 does not own:
- conscious speech Goal/Action selection (#328)
- What-to-say (#362)
- How-to-say (#330)
- semantic observation truth (#363)
- Voice Style / Performance intent (#331)
- provider-specific synthesis (#358)
- generic Actual Execution Fact authority (#329)
- Body motion / viseme generation (#340)

---

## 3. SpeechPreparationRequest

Speech preparation starts only from a committed Speech intent / eligible runtime request.

```text
SpeechPreparationRequest
- preparation_id
- source_decision_id
- speech_intent_ref
- source_event_ids[]
- source_context_revision
- goal_revision?
- attention_revision?
- priority
- interruptibility
- required_preconditions[]
- expiry_policy
- semantic_verification_policy_ref
- presentation_policy_ref
- created_at
- trace_id
```

`priority` / `interruptibility` come from committed Executive/runtime scheduling authority. #348 does not infer them from raw text.

raw user text is not a Speech Runtime decision input.

---

## 4. Component readiness model

Speech candidate progression is **not** represented as one serial phase per upstream module.

Each candidate has independent component state.

```text
SpeechComponentReadiness
- semantics: PENDING | READY | FAILED | STALE | CANCELLED
- character: PENDING | READY | FAILED | STALE | CANCELLED
- verifier: NOT_REQUIRED | PENDING | ACCEPTED | REJECTED | FAILED | STALE | CANCELLED
- performance: PENDING | READY | FAILED | STALE | CANCELLED
- audio: NOT_REQUESTED | PENDING | READY | FAILED | STALE | DISCARDED | CANCELLED
```

Logical dependencies remain:
- Character requires SpeechSemanticPlan.
- Verifier requires CharacterUtterance + SpeechSemanticPlan.
- Performance requires CharacterUtterance.
- TTS requires CharacterUtterance + SpeechPerformancePlan.

But after Character completes:

```text
CharacterUtterance
├─ #363 verifier
└─ #331 performance → #358 TTS preparation
```

may overlap.

---

## 5. Candidate lifecycle

Aggregate candidate lifecycle:

```text
PREPARING
→ PREPARED
→ QUEUED
→ REVALIDATING
→ READY_TO_PRESENT
→ PRESENTING
→ COMPLETED
```

Terminal/alternate:

```text
CANCELLED
SUPERSEDED
STALE
REJECTED
FAILED
INTERRUPTED
```

Lifecycle constraints:
- no transition from terminal state back to active.
- PREPARED does not mean spoken.
- READY_TO_PRESENT requires current live revalidation.
- PRESENTING requires one successful Presentation commit.
- COMPLETED requires trusted Presentation completion report.
- stale after external effect started must not erase that effect.

---

## 6. PreparedSpeechCandidate

```text
PreparedSpeechCandidate
- candidate_id
- preparation_id
- source_decision_id
- source_event_ids[]
- speech_plan_id
- utterance_id
- performance_plan_id
- revisions
- priority
- interruptibility
- expiry_policy
- required_preconditions[]
- semantic_verification_requirement
- semantic_acceptance_ref?
- prepared_audio_ref?
- presentation_mode_capabilities[]
- lifecycle
- created_at
- updated_at
```

Candidate references immutable artifacts; large raw audio/provider objects are not embedded.

---

## 7. Semantic verification policy

Verifier invocation is policy-driven, not ad-hoc.

```text
SemanticVerificationRequirement
- REQUIRED
- NOT_REQUIRED_BY_CLOSED_POLICY
```

When verification is not required, record:
- policy_id/version
- reason code
- exact closed conditions that allowed skip

Do not allow:
- caller boolean `skip_verifier=true` without policy proof
- Character/provider self-approval
- free-form LLM statement as skip authority

If REQUIRED:
- Presentation commit is blocked until #363 closed acceptance is ACCEPTED.
- Performance and policy-permitted TTS prep may proceed in parallel.

---

## 8. Semantic repair / regeneration

#348 owns runtime repair orchestration, but does not change semantic truth.

### 8.1 Recoverable Character realization failure

When #363 returns a closed rejection that indicates Character realization drift and the original SpeechSemanticPlan is still live:

```text
same SpeechSemanticPlan
+ bounded typed repair constraints derived from #363 observation
→ regenerate #330 CharacterUtterance
→ re-run #363
```

Repair input must be typed/closed and evidence-grounded.

Do not pass a verifier free-form instruction as new What-to-say Authority.

### 8.2 Upstream semantic invalidity

If current facts/revisions invalidate the SpeechSemanticPlan itself:
- do not repair by paraphrase.
- mark candidate STALE/REJECTED.
- emit typed replan/redecision event to the owning upstream layer.

#348 does not rewrite propositions.

### 8.3 Bounded attempts

Each preparation has explicit maximum regeneration attempts.

Initial policy:
- bounded finite attempts
- exact attempt count observable
- repeated same rejection class may stop early
- no infinite Character↔Verifier loop
- no generic fixed-phrase fallback

On regeneration:
- old performance plan becomes superseded
- old speculative audio becomes DISCARDED
- new utterance/performance/audio get new identities

---

## 9. TTS preparation policy

TTS preparation may be:
- deferred until semantic acceptance
- started after performance plan as speculative work

according to closed `TTSPreparationPolicy`.

Speculative audio artifact must be candidate-scoped and identity-bound to:
- utterance_id
- performance_plan_id
- voice binding/config revision
- pronunciation configuration revision when applicable

If verifier rejects, candidate becomes stale, or performance is replanned:
- artifact is discarded
- it must never be presented

Prepared audio is not proof of speech.

---

## 10. Presentation capability / degradation

#348 consumes a bounded `SpeechPresentationCapabilityView`.

Possible capabilities may include:
- text/subtitle presentation
- audio presentation
- timing publication

Provider/output availability is not decided by #348.

Presentation policy determines allowed modes, e.g.:
- AUDIO_WITH_TEXT preferred
- TEXT_ONLY allowed during TTS degradation
- FAIL_CLOSED if audio is mandatory for a specific use case

A degraded text-only presentation must be explicitly recorded and must not pretend audio playback occurred.

---

## 11. Queue / backpressure

Speech future generation is bounded.

Initial invariant:
- at most one active presentation per output channel
- immediate next prepared candidate is bounded
- future/background prepared candidates are bounded by queue policy
- unlimited autonomous speech pre-generation forbidden

Pressure actions:
- drop stale
- cancel/supersede low-priority candidates
- coalesce same-intent candidates only when semantic identity allows
- suppress new background preparation

Foreground direct-user response may outrank background autonomous speech.

Fairness prevents permanent starvation, but fairness does not force obsolete speech to be presented.

---

## 12. Pre-presentation revalidation

Before READY_TO_PRESENT / Presentation commit, obtain a **live** immutable revalidation snapshot.

```text
SpeechPresentationCommitState
- current source_context_revision
- current goal_revision?
- current attention_revision?
- current turn/focus state
- current required preconditions
- current output/TTS capability
- candidate cancellation/supersede state
- current Character definition compatibility
- current expression context revision?
- observed_at
```

Check at minimum:
- candidate not terminal/cancelled/superseded
- expiry valid
- source/goal/attention freshness policy
- turn ownership / response obligation
- required preconditions
- output capability
- semantic acceptance exact candidate identity
- audio artifact exact utterance/performance identity

Do not rely only on the snapshot captured before long awaits.

---

## 13. Expression drift / performance rebind

Normal Internal State evolution should not automatically force semantic regeneration.

If CharacterUtterance remains valid but current expression revision has materially drifted before Presentation, policy may perform:

```text
same CharacterUtterance
+ latest SpeechExpressionContext
→ #331 re-plan Performance
→ invalidate old audio
→ #358 reprepare if audio required
```

This is performance rebind, not speech semantic rewrite.

If delay/priority makes reprepare no longer useful, candidate may be cancelled/superseded instead.

---

## 14. Presentation commit

Presentation commit is a short atomic decision boundary.

Success conditions:
- exact candidate identity still current
- revalidation PASS
- semantic policy satisfied
- required presentation artifacts ready
- no higher-authority cancellation/supersede
- output channel accepts presentation

Commit returns a `SpeechPresentationCommand` referencing immutable candidate assets.

No long TTS/playback await occurs inside the commit lock.

---

## 15. Presentation snapshotとActual Factの境界（#657）

#348がPresentationのlifecycleを確定し、システム全体のActual Execution Factの正規化は引き続き#329だけが所有する。#657は#348が現在確定している状態を読み、独自の失敗・取消・timeout判定を行わない。

正規入力は`project_speech_execution_observation(runtime, presentation_id, provenance)`とする。`SpeechRuntime.presentation_snapshot(presentation_id)`が既存Owner lock内で返す確定command・current candidate・受理済みreport historyを一つのconsistent snapshotとして解釈する。callerからcommand/reportを別々に受け取る入口は作らない。report有無で別Authority経路を設けない。

current lifecycleは#348 Owner fact、report historyはeffect・時刻・終端理由の証拠である。commandのpresentation_idと要求ID、candidate/utterance、reportのpresentation/candidate/mode/audio identityを照合する。current candidateのaudio参照も照合し、OwnerがFAILED/CANCELLEDを確定し、audio readinessがDISCARDEDかつ参照がNoneのときだけ、回収済み資源を開始時のcommand/report証拠へ付け替えずに扱う。discard後も開始時の確認済みeffectを失わない。別assetへの変更は拒否する。

source contractはcomposition側の`speech-presentation-report@1`を使う。登録済みsource ruleはOBSERVABLE / COMPLETED / CANCELLED / FAILEDと、text-presentation / audio-presentation-startedのOBSERVABLE effectだけを許可し、終端前の確認済みeffectを必須にする。#329 CoreへSpeech型を持ち込まない。

許可するreport historyは、空系列、FAILED_BEFORE_START一件、STARTED一件、STARTEDの後にCOMPLETED / FAILED_AFTER_START / INTERRUPTEDのいずれか一件だけである。これ以外の並びや件数は拒否する。

| 受理済みreport history | current candidate.lifecycle | 汎用観測への投影 |
| --- | --- | --- |
| 空系列 | commit済み、外部提示開始の証拠なし | None。Actual Fact・effectなし |
| FAILED_BEFORE_START | FAILED | None。Actual Fact・effectなし |
| STARTED | PRESENTING | OBSERVABLE。modeに対応する確認済みeffectを導入 |
| STARTED → COMPLETED | COMPLETED | COMPLETED。先行effect refs保持 |
| STARTED → INTERRUPTED | INTERRUPTED | CANCELLED。partial effect保持、details.codeはinterrupted |
| STARTED → FAILED_AFTER_START | FAILED | FAILED。partial effect保持 |
| STARTEDのみ、終端reportなし | FAILED | FAILED。details.codeはpresentation_owner_failed_after_start |
| STARTEDのみ、終端reportなし | CANCELLED | CANCELLED。details.codeはpresentation_owner_cancelled_after_start |

終端reportがある場合はcurrent lifecycleとの一致を必須にし、不一致をreportだけで救済しない。STARTEDのみの場合も上表以外のcurrent lifecycleを推測変換しない。終端report欠落時のFAILEDは既存`SpeechPresentationExecutor` → `fail_presentation_stream()`等で#348が確定した状態であり、projectorが新たに失敗を決める意味ではない。CANCELLEDも#348の公開取消経路が明示確定した場合だけ投影する。fake FAILED_AFTER_START等のreportを生成しない。

STARTED/PRESENTINGのsnapshotを#329へ受理させてから、終端snapshotを受理させる。終端snapshotは新effectやuncertaintyを導入せず、#329に既存の確認済みeffectを保持する。TEXT_ONLYはtext effectだけ、AUDIO_WITH_TEXTはtextとaudio開始の別effectを持つ。それ以外のmode構成は拒否する。

effect identityはpresentation identityとtext/audio種別の固定JSON配列符号化から決定する。payloadはpresentation_id / candidate_id / utterance_idと音声時のaudio_refだけを保持し、発話全文やProvider objectはコピーしない。観測identityはpresentation identityと閉じたstatus分類codeから決定し、同一snapshotの再投影は同じidentity/contentとなる。

時刻はcommand.committed_at、受理済みSTARTED.started_at、受理済みterminal.completed_atを使う。終端reportのcompleted_atがない場合と、STARTEDのみでOwnerがFAILED/CANCELLEDを確定済みの場合はcandidate.updated_atを使う。candidate.updated_at ≥ STARTED.started_atを必須とし、committed_atから開始・観測時刻までの逆行も拒否する。必要なOwner時刻が得られない場合にprojectorの現在時刻で補わない。

source decision / source event IDs / source_context_revision / goal_revision / attention_revisionはcandidateとexact照合する。trace IDはintegration envelopeに存在する場合だけ保持し、推測生成しない。自由文failure_code/interruption_reasonやraw exceptionは転記せず、上表の固定details.codeを使う。

Presentation terminal-report timeoutは#659で本節の二段階watchdogとして#348 lifecycle Ownerが所有する。#657にはsleep / wait_for / deadline timer / timeout秒数を追加せず、timeoutやplayback failureを判定せず、Speech lifecycleを更新しない。#613はこのprojectorを再利用し、mappingを独自解釈しない。

---

## 16. Body / viseme publication

Only committed/started Presentation may drive actual mouth timing.

```text
SpeechPresentation STARTED
+ #358 actual pronunciation/timing track
→ #340 Body Realtime viseme lane
```

Speculative audio/timing must not move the mouth before Presentation commit.

Full-body motion/gaze/blink/breath continue independently.

---

## 17. Interruption

Current Presentation follows trusted `priority / interruptibility / turn` policy.

Possible operational actions:
- continue
- soft finish
- interrupt

New user input does not mechanically interrupt every speech; #333 Focus/Turn and committed scheduling metadata participate.

When interrupted after start:
- preserve actual presented portion/report
- cancel remaining playback where capability permits
- publish interruption result
- do not record full utterance as completed if not fully presented

---

## 18. Cancellation / supersede

Cancellation propagates candidate-locally to:
- in-flight #362/#330/#363 work when cancellable
- #331 plan work
- #358 synthesis
- queued Presentation

No global cancellation of unrelated speech/work.

Late result from cancelled/superseded task:
- may be observed for diagnostics
- must not become current candidate artifact

---

## 19. Concurrency invariants

- Speech A playback does not block Speech B cognition/preparation.
- #363 and #331 run in parallel after Character when possible.
- #358 safe TTS prep can overlap #363 according to policy.
- slow TTS does not block Input Meaning/Executive/Body.
- slow verifier does not block current playback or Body.
- Speech and Body planning are sibling fan-out from Executive.
- no Core-global speech lock across awaits.
- bounded per-candidate short locks only for lifecycle/commit transitions.

---

## 20. Observability

Required events:

```text
speech_preparation_requested
semantics_started/completed/failed
character_started/completed/failed
verifier_started/accepted/rejected/failed
performance_started/completed/failed
tts_started/completed/failed/discarded
candidate_prepared
candidate_queued
candidate_revalidation_started/completed
candidate_ready_to_present
presentation_committed
presentation_started
presentation_completed/interrupted/failed
candidate_cancelled/superseded/stale
repair_attempt_started/completed
```

Metrics:
- queue wait per component
- provider latency
- user input→first preparation
- user input→presentation start
- previous playback→next generation start overlap
- verifier repair count
- speculative TTS discard rate
- prepared candidate discard rate
- p50/p95/p99 critical path
- foreground/background starvation metrics

---

## 21. Required tests

### Lifecycle
- valid PREPARING→PREPARED→QUEUED→READY→PRESENTING→COMPLETED
- terminal state cannot reactivate
- prepared != presented
- duplicate Presentation commit rejected

### Parallel readiness
- slow verifier while Performance completes
- slow verifier while policy-permitted TTS completes
- previous 5s/20s playback while next Character/Verifier/Performance run

### Semantic repair
- recoverable #363 rejection causes bounded #330 regeneration with same Plan
- typed repair evidence only
- max attempt stop
- old performance/audio discarded after regeneration
- upstream semantic stale does not get paraphrase-repaired

### Freshness
- source/goal/attention stale reject
- turn/focus change revalidation
- expression-only drift rebinds Performance without semantic rewrite where policy allows
- stale audio identity reject

### Queue/backpressure
- bounded queue
- foreground outranks background
- stale background candidate discarded
- no call explosion under burst

### TTS/presentation
- verifier FAIL prevents speculative audio presentation
- TTS unavailable typed degradation
- text-only mode truthfully records no audio
- failed-after-start preserves partial effect

### Body/actual facts
- speculative timing does not drive viseme
- Presentation STARTED allows timing→#340
- #329 receives trusted presentation report, not prepared candidate

### Shutdown
- cancellation leaves no pending speech tasks
- retry/synthesis loops do not block shutdown

---

## 22. Non-goals

- Speech proposition generation
- Character text generation
- Semantic observer logic
- Voice performance calculation itself
- Provider synthesis implementation
- Body motion generation
- Goal/Attention authority
- finite fixed response fallback

---

## 23. Design Gate

#348 implementation starts only after:
- #331 / #358 detailed contracts align with this document
- #330 / #363 active-lineage canonical documents are reconciled
- #322/#333 lifecycle/priority semantics remain compatible
- #329 Actual Fact boundary is confirmed
- #445 Design Completion Gate PASS

#348 detailed design completion alone does not lift the global Implementation Freeze.


## Presentation局所の二段階watchdog（#659）

ユーザー承認: APPROVED 2026-09-12。timeoutとlifecycleのAuthorityは#348 Speech Runtimeのみとする。
Presentation commitから完了までの単一期限にはせず、`START_WAIT → STARTED受理 → TERMINAL_WAIT → terminal`で閉じる。

`SpeechRuntimeOperationalPolicy.presentation_timeout`は不変の`SpeechPresentationTimeoutPolicy`であり、既存の`policy_id / policy_revision`のgenerationに含む。
承認されたproduction初期値は次のとおり。各値はboolを除くint/float、有限、正数を必須とする。

| フィールド | 秒 |
| --- | ---: |
| start_report_timeout_seconds | 5.0 |
| text_terminal_timeout_seconds | 5.0 |
| audio_terminal_grace_seconds | 5.0 |
| audio_terminal_fallback_timeout_seconds | 60.0 |

commit成功時のOwner clockをSTART_WAITの起点とし、policy identity/revision・全timeout値・candidate generation・音声durationをPresentation局所に固定する。
current policyを更新してもactive Presentationの期限は伸縮しない。後続Presentationは新generationを使用する。
`SpeechPresentationCommitState.observed_at`、commandの`committed_at`、Adapter timestampはwatchdogの時計Authorityにしない。

START_WAITではSTARTEDまたはFAILED_BEFORE_STARTだけを最初のreportとして受理する。
有効first reportが期限までに受理されなければ、OwnerがFAILEDへ閉じ、START_WAIT診断を記録する。
report historyは空のまま。#657 projectorはNoneであり、#329のActual Execution Factや外部effectを捏造しない。
FAILED_BEFORE_STARTを期限前に受理した場合は通常terminalでありtimeout診断を作らない。

STARTEDを正式受理したOwner時刻からTERMINAL_WAITを開始する。reportのstarted_atはevidenceとして保持するが、deadlineの起点にはしない。
TEXT_ONLYは受理時刻+5秒。AUDIO_WITH_TEXTは信頼された実音声durationがあれば受理時刻+duration_ms/1000+5秒grace、なければ受理時刻+60秒とする。
既存#358の`PreparedAudioArtifact.duration_ms`は正のint（bool禁止）のmillisecondsであり、その意味を変更しない。
既存`CandidateArtifactStore.current_artifact(candidate_id)`にはtyped artifactがあるが、現行Presentation compositionにはduration transportがない。
`SpeechPresentationCommitState.prepared_audio_duration_ms`をoptional metadata境界として設け、同じstateの`prepared_audio_ref`およびcurrent candidateのaudio_refとのexact bindingを必須とする。
trusted metadata供給側は既存artifactを使い、参照文字列・file size・textからdurationを推測しない。TEXT_ONLYではaudio durationを期限Authorityにしない。
#358 Providerの意味や#613 integration wiringはこのWorkでは変更しない。

report受理と期限解決は同じOwner lock内で行う。`owner_now < deadline`なら通常受理、`owner_now >= deadline`ならtimeoutを優先する。
report timestampが過去でもOwnerへの到着を遡らせない。確定済みterminalはtimeoutで上書きしない。
TERMINAL_WAIT timeoutではFAILEDへ閉じ、受理済みSTARTEDだけを保持する。fake STARTED/COMPLETED/FAILED_AFTER_START、追加effect、推測uncertaintyは生成しない。
#657の既存snapshot projectorがSTARTED-onlyとOwner FAILEDをgeneric FAILEDへ投影し、#329が先行OBSERVABLEで受理したtext/audio partial effectを保持する。
新しいCandidateLifecycle、Foundation ExecutionStatus、第二のPresentation/Actual Fact Authorityは作らない。

Ownerの`presentation_wait_seconds`と`expire_presentation_if_due`はPresentation/candidate identity、candidate generation、固定policy generation、current lifecycle、受理済みreports、Owner時刻、期限を同じatomic境界で照合する。
`SpeechPresentationTimeoutRecord`は不変の診断で、Presentation/candidate identity、START_WAIT/TERMINAL_WAIT、awareなdeadline/detected_at、固定policy identity/revisionを持つ。detected_atはdeadline以後。timeout以外では生成せず、Actual Factとは区別する。

Executorはcandidate局所の実行Sessionから次reportを待ち、Ownerの期限を同じatomic境界で解決する。OS process/PID/signalはDomain契約へ出さない。

### 別プロセス実行境界（ユーザー承認、#659 Test/Fix）

親のSpeech Runtimeがlifecycle/deadline/terminal claimのAuthorityを保持する。Domainは`SpeechPresentationExecutionBoundary`と`SpeechPresentationExecutionSession`のPortのみを所有し、Sessionのclose完了は外部実行と通信資源の回収済みを意味する。
InfrastructureのSupervisorが1 Presentationごとに明示worker moduleを`sys.executable -m`で起動する。poolは導入しない。具体Adapterの生成・SDK・device/surface I/Oは子だけで実行する。
既存production Presentation登録はまだないため、信頼された構成側がadapter kind・import可能なfactoryのmodule/name・JSON configurationを明示登録する。任意callable/objectのpicklingは使用しない。登録をユーザー入力やreportから選ばず、#613のproduction wiringと#358のTTS生成は先取りしない。

親子間はversion 1のJSONL envelopeとし、schema、version、kind、utterance_id、correlation_id、payloadを必須とする。correlation_idはpresentation_idにexact bindし、command/reportのcandidate・asset identityはOwnerでも再照合する。
codecはDomain DTO外に置く。messageは64KiBを上限とし、重複key・未知field・不正数値・不正identityを拒否する。stdoutはprotocol専用とし、Adapter/SDKのstdoutをfd単位でstderrへ隔離する。現SupervisorはstderrをDEVNULLへ破棄し、raw外部出力・外部例外をAuthorityや診断の説明へ採用しない。必要な診断はtyped code等の安全な診断経路だけで扱う。
spawn成功をSTARTEDへ昇格しない。Adapterが実際に返すreportだけをOwnerへ渡す。起動不能・不正protocol時の同一process fallbackは禁止する。

正常terminal後も子の終了とpipe回収を待つ。timeout/取消/shutdownでは、入力EOFによる停止要求 → bounded grace → terminate → bounded wait → kill → bounded reapを実施する。
回収対象はworkerの直接PIDだけでなく、Adapter/SDKが通常生成するdescendant process全体を含む。POSIXでは`start_new_session=True`で専用session/process groupを作り、group全体へSIGTERM、必要ならSIGKILLを送り、workerのwaitとgroup消滅を確認する。workerが先に正常終了していてもgroup内のhelperを残さない。
Windowsでは専用の非継承・無名Job Objectを作成し、`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`を設定する。breakawayを許可しない。workerはcommand受信までAdapterをimport/生成せず、親はJob割当成功後だけcommandを送る。割当失敗時は実行を拒否し、command未送信のbootstrap workerを回収する。通常のexecution回収は`TerminateJobObject`でdescendantを含めて終了させ、workerのwaitとJobの`ActiveProcesses == 0`を確認した後にhandleを閉じる。Windowsのterminate/kill段階はいずれもJob全体の強制終了であり、direct `Process.kill()`を同等保証と扱わない。Job割当がOS/既存Jobの制約で拒否される環境ではSPAWN_FAILEDとし、同一processへfallbackしない。
Presentation Adapter/SDKが起動するprocessはexecution containmentから離脱してはならない。POSIXのsetsid/setpgidによる離脱、Windowsのbreakaway、外部常駐サービスへの独立process起動委譲等を禁止する。意図的に離脱するprocessの回収は保証対象外であり、このAdapter契約を満たさない実装は登録対象にしない。OS APIはInfrastructureだけが所有する。
cleanup秒数は固定policy generation内の`worker_grace_seconds=0.2`、`worker_terminate_seconds=1.0`、`worker_kill_seconds=1.0`へ集約する。これは実装時に設定したcleanupの初期値であり、承認済みPresentation deadline 5/5/5/60秒を変更しない。
親側取消・再取消でもcleanupはshieldして完了まで回収する。timeoutのOwner claimを先に確定し、後着reportは上書きしない。呼出元へのterminal待機復帰はcleanup後とし、対象の生存子PID・tracked task・open IPC・子所有Adapter I/Oを残さない。
OSがkill後も回収完了を返さない場合に加え、stdin閉鎖待機・stdout drain・containment照会/終了・handle閉鎖の失敗は、`diagnostics.failure = CLEANUP_FAILED`と`PresentationExecutionError(CLEANUP_FAILED)`へ収束する。raw TimeoutErrorを公開契約へ出さない。drain taskは失敗時もcancelしてjoinする。`diagnostics.closed`をTrueにせず、SessionをSupervisor追跡から削除せず、成功postconditionを主張しない。
POSIXの実process試験とWindows Job API境界のunit testは証拠を区別する。Windows実機で未実行の場合、その実機回収・OS互換性は検証済みと記録しない。

失敗はtyped codeでspawn、encode、protocol/identity、STARTED前後の異常終了、Adapter failure、terminal欠落、timeout、shutdownを区別する。terminate/kill実行はSupervisor診断として保持する。raw stderrやfree-form例外をAuthorityにしない。
実際に取消拒否・terminate無視する子をtimeout/shutdownからkill/reapし、通常・失敗・race・反復実行・unrelated進行と#657/#329 partial effect保持を検証する。
既存の同一process Adapter検証は明示的な検証専用Sessionでのみ実施し、production Supervisorからfallbackしない。
