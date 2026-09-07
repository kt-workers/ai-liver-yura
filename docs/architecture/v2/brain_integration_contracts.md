# V2 Brain Integration Contracts

Owner Issue: #334
Parent: #325
Upstream: #326 / #327 / #328 / #366 / #361 / #329 / #362 / #330 / #363 / #331 / #332 / #364 / #333 / #348
Related: #322 / #323 / #350 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

#334はBrain各Moduleを、Authorityを保ったまま**event-driven / snapshot-based / sparse activation / non-serial**に結合するIntegration契約を定義する。

Integrationは「Cognitive Loop」という新しい万能判断Authorityを作らない。

```text
Typed Event / internal trigger
        ↓
#326 Meaning ───────────────┐
        ↓                   │
#327 Appraisal/State        │
        ↓ salience          │
#333 Attention/Turn ←───────┤
        ↓ eligible trigger  │
#328 Executive              │
   ├─ Goal transition → #366
   ├─ optional Plan → #361 → #329
   ├─ Speech intent → #362/#330/#363/#331/#348
   └─ Attention intent → #333

#332 Memory evidence ───────→ #326/#327/#328 bounded context
#364 Reflection ← historical trusted results (background)
```

矢印はAuthority/data dependencyであり、全段を1 request内で順番にawaitする意味ではない。

---

## 2. Integration owns / does not own

### #334 owns

- module composition/wiring
- typed trigger routing
- immutable snapshot acquisition coordination
- cross-module identity/revision propagation
- background/foreground lane admission integration
- cancellation/supersede propagation wiring
- integration trace/timeline
- fake-provider integration topology
- degraded optional-module routing

### #334 does not own

- NL meaning (#326)
- current Internal State (#327)
- Goal/Action decision (#328)
- Goal/Commitment state (#366)
- Attention/Turn state (#333)
- Plan semantics (#361)
- Activity execution truth (#329)
- What-to-say (#362)
- Character realization (#330)
- semantic observation (#363)
- Performance (#331)
- Memory canonical state (#332)
- Reflection candidate judgment (#364)
- Speech presentation lifecycle (#348)

Integration code must not contain fallback decision logic that duplicates those owners.

---

## 3. Brain integration envelope

Cross-module work carries a shared correlation envelope.

```text
BrainWorkEnvelope
- trace_id
- trigger_id
- source_event_ids[]
- source_context_revision
- goal_revision
- attention_revision
- priority
- created_at
```

Module-native revisions remain separate where required:
- internal_state_revision
- memory/retrieval snapshot identity
- character definition revision
- speech plan/utterance identity

One global revision is not used to replace owner-native revisions.

---

## 4. Trigger sources

Executive is not triggered only by user text.

Eligible typed source classes include:

```text
EXTERNAL_INPUT
ATTENTION_ELIGIBLE_EVENT
GOAL_COMMITMENT_REVIEW
ACTIVITY_RESULT
EXTERNAL_OBSERVATION
INTERNAL_STATE_THRESHOLD_OR_CHANGE
MEMORY_RELEVANCE_SIGNAL
SYSTEM_LIFECYCLE_SIGNAL
```

Trigger eligibility is determined by owning contracts (#333 etc.), not a raw event-type string switch that reinterprets meaning.

Pending Goal/Commitment may create an autonomy trigger without user input.

---

## 5. Input / Meaning / Appraisal flow

External natural-language input:

```text
Input Gateway
→ #326 StructuredInputMeaning
→ #327 Appraisal candidate/reducer
→ #333 salience/attention scheduling
→ eligible Executive trigger
```

Rules:
- Executive never receives raw text as alternate semantic Authority.
- Input Meaning completion is not a global barrier for unrelated ongoing work.
- a slow Meaning request does not stop current Speech presentation, Body, Game or other independent input reception.
- same source event cannot be committed twice as conflicting Meaning generations without owner rules.

---

## 6. Internal State integration

#327 owns state mutation.

Integration passes:
- typed Meaning/evidence
- Memory evidence where requested
- Activity/external observation evidence

to #327 through its contract.

State updates can independently generate:
- Appraisal/State read models
- salience candidates
- later Executive triggers
- Body expression inputs

No integration callback writes state directly.

---

## 7. Attention / Turn integration

#333 sits between high-volume event sources and Executive eligibility.

```text
salience hints + current Goal/Activity/Turn
→ #333 bounded scheduling
→ ExecutiveTrigger
```

Integration rules:
- not every event invokes Executive.
- direct user interaction may outrank background Reflection.
- Game/Streaming burst uses bounded inputs.
- Body gaze is downstream projection only.
- stale attention revision is propagated to relevant long-running work and checked by owner commit gates.

---

## 8. Executive fan-out

A committed Executive decision may contain multiple sibling intents.

```text
CommittedExecutiveDecision
├─ Goal/Commitment transition → #366
├─ Activity/Planning path
├─ Speech path
├─ Body path (outside #334 integration scope, consumed by #341)
└─ Attention intent → #333
```

Sibling work may begin in parallel where their prerequisites are satisfied.

Character/Speech completion is not prerequisite for Body intent dispatch.

Goal transition application ordering must respect #366 expected revision semantics. If a sibling Plan requires the new Goal revision, it starts only after that revision is committed; unrelated siblings need not wait.

---

## 9. Goal / Planning / Activity integration

```text
Executive transition intent
→ #366 atomic state apply
→ current GoalContextView

Executive Activity intent
or active complex Goal requiring decomposition
→ #361 planning
→ #329 Activity admission/execution
→ Actual Execution Fact / result event
→ #327/#333/#328 as evidence/trigger
```

Rules:
- #361 cannot change Goal.
- stale `goal_revision` Plan rejected.
- #329 execution result does not auto-complete Goal; Executive/#366 transition required.
- capability unavailable returns evidence for later decision; Integration does not silently choose another Goal.

---

## 10. Speech integration

Speech path uses D2 contracts.

```text
Executive SpeechIntent
→ #362 SpeechSemanticPlan
→ #330 CharacterUtterance
   ├─ #363 semantic observation
   └─ #331 performance
→ #348 readiness / queue / revalidation / Presentation
```

Simple path may avoid a dedicated #362 LLM while still producing the same `SpeechSemanticPlan` Authority contract.

#334 does not require actual TTS/Avatar for minimum Brain text Integration. #348 can use a fake/text Presentation adapter for deterministic Integration.

Human Character quality is not #334 automated acceptance.

---

## 11. Memory integration

### Retrieval

Owner modules request bounded `MemoryEvidenceView` from #332.

- Input Meaning: reference/context evidence
- Appraisal: historical contextual evidence
- Executive: bounded relevant evidence

Memory does not select Goal or set current State.

### Reflection

Historical trusted outcomes are submitted to #364 asynchronously.

```text
Activity/Speech/external result
→ Reflection source queue
→ #364 candidate/support gate
→ #332 Store
```

Reflection is never a foreground response dependency.

---

## 12. Work scheduling model

Initial logical lanes:

```text
FOREGROUND_INTERACTION
COGNITIVE_NORMAL
SPEECH_PREPARATION
BACKGROUND_REFLECTION
```

These are scheduling categories, not Domain Authorities.

#322 owns queue/priority/backpressure mechanics.

Integration maps module work to scheduler metadata from trusted owner inputs.

No single global async lock surrounds Brain cognition.

---

## 13. Sparse LLM activation

Logical Role presence does not imply API call every cycle.

Examples:
- simple typed response semantics can use deterministic #362 path
- Appraisal may use deterministic reducer without deep LLM if evidence sufficient
- Planner only for complex decomposition
- Reflection only at background policy points
- Verifier according to explicit semantic-risk policy

Integration does not infer open-ended semantics to skip an owner Role; activation policy is explicit/typed.

---

## 14. Stale / cancel / supersede propagation

Long-running work records relevant revisions.

### Hard stale examples
- source input/reference changed
- Goal revision invalidates Plan
- Attention/Turn ownership invalidates queued response
- candidate explicitly superseded
- owner precondition/capability changed where required

### Non-global stale
A revision change only invalidates work whose owner contract declares dependency on that revision.

Example:
- unrelated Memory write does not cancel current Speech.
- current BodyState realtime revision does not invalidate all Brain work.

Integration never implements `any revision changed -> cancel everything`.

---

## 15. Degraded optional dependencies

Brain minimum text cognition must support:
- no TTS
- no Avatar
- no DB persistence
- no Plugin
- no Streaming/Game

Memory persistence unavailable:
- #332/#359 expose degradation; current interaction can continue if safe.

LLM提供サービスが利用できない場合:
- 影響を受ける役割は型付き失敗を返す。
- 入力意味解析の本番境界では`InputMeaningInterpretationResult`を受け取り、`meaning / role_failure / boundary_failure`を型で判定する（#564）。
- 統合側は架空の`StructuredInputMeaning`や確認要求を生成せず、例外文字列を解析せず、サービス失敗を成功へ書き換えない。
- 影響を受けない処理経路は継続できる。失敗の分類と採用判断は各所有者の契約に従う。

---

## 16. Execution and observation return loop

Results from Activity/Subsystem/Speech presentation become typed evidence/events.

```text
trusted result/observation
→ event/fact projection
→ Appraisal and/or Attention
→ optional Executive trigger
```

Integration does not automatically translate every success into a new Goal transition.

Intent/Plan/generated speech cannot substitute for actual result evidence.

---

## 17. BrainIntegrationTrace

```text
BrainIntegrationTrace
- trace_id
- root_trigger_id
- source_event_ids[]
- intervals[]
- revision_events[]
- decision_ids[]
- goal_transition_ids[]
- activity_ids[]
- speech_candidate_ids[]
- terminal_outcome
```

Work interval:

```text
BrainWorkInterval
- work_id
- module
- lane
- queued_at?
- started_at
- completed_at?
- status
- source_context_revision?
- goal_revision?
- attention_revision?
```

Tracing is read-only evidence and not state Authority.

---

## 18. Integration fake topology

Minimum deterministic setup:
- fake Input Gateway/events
- fake/deterministic Meaning/Appraisal/Executive roles where needed
- real Domain Authorities/stores
- fake LLM Port with controllable delay/result
- fake Capability execution adapter
- fake text Presentation adapter
- in-memory Memory repository
- fake clock

TTS/Body/Avatar/Streaming are not mandatory for #334 minimum Brain Integration.

---

## 19. Required scenarios

### Cognition
- normal question/answer
- user request not treated as unconditional command
- clarification required
- farewell
- reference such as prior-action request using bounded Memory/Context
- capability unavailable

### Persistent autonomy
- Goal persists across turns
- suspend/resume/complete/abandon/supersede
- pending Goal/Commitment creates internal trigger without user input

### Responsibility
- Meaning vs Appraisal
- Executive vs Goal Store vs Planner
- Goal vs Activity
- What-to-say vs How-to-say
- Verifier observer only
- Reflection vs Memory Store

### Concurrency
- slow Deep Appraisal while new input accepted
- slow Planner while current Speech/unrelated work continues
- slow Verifier while safe Speech preparation continues
- slow Reflection while foreground conversation completes
- background LLM burst without foreground starvation
- Speech A presenting while Speech B preparation begins

### Freshness
- stale source context result reject
- stale goal revision Plan reject
- stale attention/turn queued speech reject
- cancelled/superseded result noncommit

---

## 20. Acceptance metrics

- event→Meaning latency
- event→Attention eligible
- event→Executive decision
- event→speech preparation
- event→Presentation
- foreground queue wait
- background starvation/fairness
- concurrent in-flight count
- stale/cancel/supersede count
- Reflection queue delay

Playback duration must not linearly postpone next Speech generation start.

---

## 21. Defect ownership

Integration failure is classified before fix:

```text
CONTRACT_MISMATCH
MODULE_DEFECT
INTEGRATION_WIRING_DEFECT
PROVIDER_DEFECT
TEST_HARNESS_DEFECT
```

If one Work's semantic/authority behavior is wrong, defect returns to that Work Issue; #334 does not absorb a local workaround.

---

## 22. #445 Gate

Brain Integration implementation remains frozen until #445 D1-D9 and final user confirmation PASS.


## 計画から活動への公開接続（#334）

本体の計画全体への承認・手順進行・命令発行は`plan_execution_approval_contracts.md`を正本とする。#334はこの公開境界を接続し、独自の判断正本を作らない。

## 23. 入力意味へ渡す参照文脈の構成と現在版

`CoreInputReferenceContextBinding`は、既存の目標読取と活動実行所有者から入力意味用の参照文脈を構成する。目標の選択は既存の`build_goal_context_view`とその上限方針へ委ねる。活動は本体の構成側が明示した命令識別子について正規の実行記録を読み、記録のない識別子は拒否する。ここでは自然言語の意味、重要度、注意、目標、完了を判断しない。

この接続が所有する`source_context_revision`は参照投影の世代であり、目標版や活動記録版の最大値・合計ではない。同じ参照投影と元の世代の組には同じ版を返し、組が変わった場合だけ単調に進める。参照項目の`revision`も投影世代を使う。元の`GoalContextView`と活動記録は同じ不変の取得結果に保持し、各所有者の版との対応を失わない。

複数所有者の読取は既存の有界な版安定化契約に従い、取得前後の所有者別の版と内容指紋を照合する。同じ版で内容が変化した場合、取得が安定しない場合、記録不在、参照数超過は失敗とし、古い文脈を最新として返さない。失敗した取得では公開済み投影を更新しない。短い同期読取と投影更新だけを保護し、LLM待機や本体全体を覆う排他を設けない。

採用方針は当該起動世代の不変な設定を正本とし、入力意味所有者へ渡すものと同じ実体を参照する。設定ファイルの書換えだけで稼働中の方針を変更しない。`current_freshness_stamp`はLLM応答後に元の所有者を再取得して文脈版を確認する。要求時の版やキャッシュだけから現在版を返さない。

最小起動もこの接続を利用し、実体のある空の目標所有者と活動所有者から開始する。目標や活動を勝手に生成せず、未提供能力や提供サービスの失敗は既存の型付き失敗のまま扱う。保存からの起動構成では、別の空の目標所有者を作らず、復元した目標読取を同じ接続へ渡す。

本節の初期対象は目標・約束と明示された活動参照である。最近の発話・提示、判断、記憶根拠の参照供給と、通常認知全体の処理登録・結果返却は後続の結合条件として保持する。最小起動での意味採用成功を本体全体の完成へ拡大しない。

## 24. 現在文脈と状態所有者から評価へ接続する

`CoreAppraisalBinding`は、同じ本体の`CoreInputReferenceContextBinding`と`InternalStateReducer`を参照し、深い評価の公開入口と状態・評価事実の同時確定を接続する。状態の初期値、評価方針、LLM提供先、時計は構成時に明示する。接続側は状態の値、自然言語の意味、目標、注意の優先度を生成しない。状態所有者の複製や要求ごとの初期化を行わない。

要求前と応答後の読取では、入力参照と内部状態を既存の有界な読取安定化契約で照合する。評価要求は確定した入力意味と元の状態を保持し、参照根拠には同じ取得結果の参照先識別子を渡す。内部状態の由来が入力文脈より古くても書き換えず、評価所有者の第13節の契約を使う。入力意味の元イベント・文脈の不一致、文脈取得不能、状態の競合は評価所有者または読取境界で拒否する。

候補の応答後検査と状態確定の間でも、現在文脈を再取得する。待機を挟まず、信頼できる時計の現在時刻を`commit_with_facts`へ渡す。評価事実のリビジョンはこの接続の起動中に成功した確定ごとに1つ進め、失敗時には進めない。状態・評価事実・元候補の組をそのまま返し、最新の成功結果を1組だけ保持する。保存した組を現在として読む際は、状態所有者と現在文脈が今も一致することを確認する。後続の状態更新があれば古い組を最新へ付け替えない。

接続は単一の本体イベントループで使用する。LLM待機を囲む排他を作らず、並行呼出しの競合は状態所有者のリビジョン検査へ委ねる。各実行は評価呼出しの子タスクを1つ所有し、呼出し側の取消・再取消でも最後まで回収する。切り離された背景タスクは残さない。取消済みの処理は要求前と応答後に確認し、提供先が取消を捕捉して結果を返しても確定しない。確定後に取消された結果は最新成功結果として保持する。既存のBrain実行へ登録する`AppraisalBrainModulePort`は処理の識別子・入力文脈・追跡識別子を検査し、実行・待ち件数・取消・停止の所有権を既存Runtimeに委ねる。

この入口は明示的に投入された深い評価だけを実行し、全入力や全判断にLLM呼出しを強制しない。定型評価、注意の選択、実行判断の起動、目標・活動・発話への分岐は既存所有者に残す。最小起動への全役割設定、確定入力意味からの自動経路、注意・判断への継続接続は後続の結合条件であり、本節単独では通常認知全体の完成としない。

## 25. 定型評価と注意の選択結果の由来

`CoreAppraisalBinding.appraise_fast`は明示した型付き規則を既存の`appraise_event`へ渡す。自然言語の意味や規則を生成せず、規則なしでは状態を更新しない。現在文脈と状態を取得し、生成された候補だけを深い評価と同じ同時確定入口へ渡す。両経路は同じ評価事実リビジョンを使い、定型評価が先に確定した場合は待機中の古い深い評価を拒否する。深い評価を定型評価や注意選択の必須前提にしない。

`CoreAttentionBinding`は同じ本体の入力参照・評価接続・注意所有者を結合する。現在性を確認できる確定済み評価だけを既存の`AppraisalAttentionProjector`で注意へ投影する。優先度、選択順序、割込み適格性、会話順序は`AttentionTurnStore`が決める。投影の受付と次の選択を分離し、投影した評価が必ず選ばれるとは扱わない。

選択時には実際の目標リビジョンを注意所有者へ渡し、返された選択識別子から同じ注意状態内の元情報を取得する。`CoreAttentionDispatch`は選ばれた`AttentionSource`と`ExecutiveTriggerEligibility`、現在の入力参照、内部状態所有者の現在状態、現在の評価結果（未提供なら`None`）を別の項目で保持する。選ばれた元情報の古い由来を現在文脈へ書き換えない。直近の評価と選ばれた元情報が異なる場合も、直近評価をその元情報の評価結果として付け替えない。`selected_appraisal`は元候補の識別子・基底リビジョン・文脈が一致する場合だけその結果を返す。

注意状態の文脈が現在の入力参照に追随していない場合は選択を行わず失敗とする。接続側が文脈を捏造して注意を更新したり、古い元情報を勝手に解消したりしない。選択後も元の注意状態と入力参照の一致を検査する。状態や評価が進んだ場合に備え、`is_current`で参照・注意・内部状態・現在評価を再取得して照合できる。接続が実際に発行した最後の搬送結果を1件だけ保持し、複製・改変された搬送結果を現在の選択証拠として受理しない。ここでの現在性確認は実行判断所有者の確定前検査を置き換えない。

これらの同期操作は本体の単一イベントループで行い、LLM待機を囲む排他を設けない。全役割の起動設定、選ばれた元情報に対応する意味・根拠を実行判断へ渡す接続、判断から目標・活動・発話へ続く経路は後続として保持する。注意の選択だけで命令や発話を発行しない。

## 26. 注意の選択結果から実行判断へ接続する

`CoreExecutiveBinding`は`CoreAttentionBinding`が発行した現在も有効な搬送結果から判断を開始する。選択元に対応する意味・根拠・能力・前提条件・計画参照は、構成時に明示した信頼済みの読取境界へ要求する。取得結果は選択元を型付きで保持し、不一致なら拒否する。選ばれた評価の元イベントが確定結果から取得できる場合と、直接のユーザー入力が選ばれた場合は、供給元が示す契機のイベント群も照合する。選択元の見出しだけが一致する別イベントの根拠を受理しない。現在の内部状態・評価事実・目標と注意のリビジョンは搬送結果を使い、供給側の固定ひな形で置き換えない。評価事実がない場合や意味の文脈が異なる場合は、生成・付け替えをせず既存の判断条件を満たさないものとして拒否する。

読取結果`CoreExecutiveEvidence`は選択元とその根拠の不変な組であり、`ExecutiveContextSnapshot`の複製ではない。容量と参照の検査は既存の`build_executive_context_snapshot`へ委ねる。読取境界は各事実の所有者に接続する責務を持ち、判断や候補を補作しない。具体的な供給元の登録と全役割の起動構成は後続の未達条件である。

LLM応答後は供給元を再取得し、意味・根拠・計画参照が要求時と同一であることを確認する。能力と前提条件は新しい値を判断所有者へ渡し、その候補が使用するものの変化を既存確定検査へ委ねる。必須要件は候補の自己申告をコピーせず、信頼済みの決定論的方針または上流契約の読取境界から取得する。取得失敗・未登録・不足時に空の要件を補う処理を禁止する。必須要件の取得を待った後にも根拠と注意搬送の現在性を確認する。

判断の確定は起動中で共有する`ExecutiveDecisionAuthority`へ委ね、同じ選択契機を二重確定しない。取消済みでは要求・確定を行わず、所有する子タスクを取消・再取消でも回収する。提供先が取消を捕捉しても、確定前の取消確認で採用を抑止する。既に確定した判断は最後の成功結果として保持する。この入口は判断結果を返すだけで命令や発話を発行せず、後続の分岐は既存の目標・計画・活動・発話の所有者へ接続する。
