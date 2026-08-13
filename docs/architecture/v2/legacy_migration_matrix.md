# AI Liver ゆら V2 Legacy Migration Matrix

Status: Draft / V2 Design Gate / Final cognitive reconciliation 2026-08-12
Root: #317
Management: #318
V2 branch: `rebuild/v2-foundation`

Canonical designs:
- `system_architecture.md`
- `brain_architecture.md`
- `cognitive_llm_architecture.md`
- `goal_commitment_architecture.md`
- `concurrency_architecture.md`
- `speech_pipeline_architecture.md`
- `body_architecture.md`
- `plugin_architecture.md`
- `subsystem_architecture.md`

## 1. 目的

旧Issue / PR / design / Verificationを捨てる前に、重要な要求・不変条件・failure knowledge・Verification条件をV2へ回収したことを証明する台帳。

V2は`main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`から新規再構築し、旧product codeをmerge/cherry-pickしない。

```text
Legacy history
→ retain requirement / invariant / failure class / test
→ V2 canonical + V2 Issue
→ new implementation
```

### Cognitive / LLM再設計で撤回した旧前提

- system-wide LLM Roleを4個固定
- 第5 LLM責務禁止
- CommanderがWhat-to-say詳細まで所有
- 責務分離LLMを毎回直列await
- current GoalをLLM context内だけで保持
- Game/Streaming高頻度EventをExecutiveへ無制限同期投入

### 新原則

- LLM Role数は独立責務から決まり固定しない
- `Logical Role != API Call`
- conscious Goal/Action Authority = Executive #328だけ
- current Goal/Commitment正本 = #366 deterministic typed state
- current Attention/Focus/Turn scheduling = #333 deterministic typed state
- What-to-say #362 / How-to-say #330 / independent observation #363
- Memory candidate #364 / Store #332
- complex Goal planning #361
- Game realtime skill #365
- Event-driven / snapshot-based / sparse activation / concurrent lanes

---

## 2. Authority snapshot

初回inventory（2026-08-12）:

- Legacy Open Issues: **44**
- initial Open PRs: **23**
- initial V2 Issues: #317〜#360
- cognitive/final-goal reconciliation additions: #361〜#366
- V2 canonical branch: `rebuild/v2-foundation`

旧Issue/PRをcloseするのはmapping・canonical reconciliation・Design Gate確認後。

---

## 3. Disposition

| 区分 | 意味 |
|---|---|
| `MIGRATE` | 要求/知見をV2へ移し旧実装はmergeしない |
| `OPS-RETAIN` | V2にも継続する運用正本 |
| `HISTORY-RETAIN` | 歴史資料。current product authorityではない |
| `TOOLING-MIGRATE` | Validation/Development Toolingへ移行 |
| `CI-ARCHIVE` | CI知見だけ回収し実装は移さない |

---

## 4. Legacy Open Issue migration

| Legacy | 残す要求・知見 | V2 destination | Disposition |
|---|---|---|---|
| #186 起動時の覚醒反応 | 固定neutral/挨拶ではなく前回状態・停止時間・現在状態からAppraisalしSpeech/Body/Silenceへ因果接続 | #327 #333 #337 #350 #359 #360 | MIGRATE |
| #187 GUI全画面最新化 | `gui/*`棚卸し、public DTO/read model、接続/切断/再接続、Render/ローカル、実画面Verification | #351 | MIGRATE |
| #189 会話生成・発話準備の因果状態 | 生成中も無反応にせずturn/process factsとExpression/Discourseを因果接続。固定考え中Motionで隠さない | #327 #333 #337 #348 #362 #330 #334 | MIGRATE |
| #190 InteractionProcessSnapshot | input/LLM/verification/TTS/presentation/turn/cancel等の実行事実をtyped revisionで観測 | #321 #322 #333 #348 | MIGRATE |
| #191 Interaction Process Appraisal | execution/process factをattention/uncertainty/commitment/readiness等へ評価し処理段階→fixed Motionにしない | #327 #333 #337 | MIGRATE |
| #192 Expression Appraisal | Emotion/Motivation/Interaction/AttentionをBody/Voice/Silence向け高レベル表現へ統合 | #337 #331 #333 | MIGRATE |
| #193 Discourse Appraisal | topic distance、response obligation、bridge、acknowledgement等をtypedに扱い固定Prefix禁止 | #327 #333 #362 | MIGRATE |
| #194 Turn-taking最終統合 | normal/autonomous/interruption/TTS failure/long generation waitを統合。turn/attentionをSystem確認 | #333 #334 #348 #360 | MIGRATE |
| #195 旧実行ロードマップ | 旧順序を正本にせず依存・Start/Target・Verification管理だけ維持 | #317 #319 | MIGRATE |
| #196 Awakening Context/Persistence | cold/restart/resume、停止時間、minimum snapshot、DB unavailableでも起動 | #327 #350 #359 | MIGRATE |
| #197 Awakening Appraisal/Lifecycle | 起動ContextをInternal Stateへ評価し固定Presetでなく因果Lifecycle | #327 | MIGRATE |
| #198 Awakening Expression/Autonomy | 覚醒状態をBody/Autonomyへ高レベル投影し固定あくび/伸び/挨拶を作らない | #337 #333 | MIGRATE |
| #199 Awakening実HTTP/SSE検証 | cold/resume/long stop/capability欠損等Integration | #352 #360 | MIGRATE |
| #201 Memory最適化 | Candidate生成、importance/novelty/persistence/confidence、route、merge/update/conflict、retrieval | #364 #332 #359 | MIGRATE |
| #207 引継ぎハブ | GitHub live authority、Issue粒度、Verification、Projects、設計整合、1 Work=1 lineage | #317運用全体 #314 | OPS-RETAIN |
| #210 内部状態への直接質問 | diagnostic label復唱でなくtyped target/current stateから自然な自己表現、target外state代用禁止 | #326 #327 #328 #362 #330 #363 | MIGRATE |
| #211 Generative Body Motion | Skeleton/DOF/limits/current pose、IK/Kinematics、full-body、no preset/home reset、3D全方向 | #335 #336 #338 #339 #341 | MIGRATE |
| #212 「もう一回」一般参照 | recent action/speech/topic/Goal/Activity/Memoryからbounded typed reference解決 | #326 #366 #329 #332 | MIGRATE |
| #213 Viseme同期 | actual TTS pronunciation→viseme timeline、Body realtimeとfull-body motion並行 | #331 #358 #340 | MIGRATE |
| #214 Character Body Style | Character設定をfixed poseでなくsoftness/trajectory/CoM/coordination等へ投影 | #354 #355 #337 | MIGRATE |
| #215 Body Pose Lab簡素化 | StickをBody contract validation mockとして利用、UIはBody判断なし | #352 #346 | TOOLING-MIGRATE |
| #217 連続接触意味区間化 | high-frequency sample数にstate changeを比例させずcontact session/semantic segment/body region | #349 #327 | MIGRATE |
| #218 会話終了誤分類 | farewell/conversation endとActivity stopをInput Meaningで分類、surface matcher禁止 | #326 | MIGRATE |
| #221 Ctrl+C/pending task | optional output切断でCore破壊なし、backoff/rate-limit/idempotent close/pendingなし | #322 #350 | MIGRATE |
| #223 Character/Validator Lab | full runtimeなしでproduction path実LLM検証、preset/export/境界観測 | #352 | TOOLING-MIGRATE |
| #225 発話内容/Character/Voice分離 | What-to-say / How-to-say / Voice performanceを分離 | #362 #330 #331 #348 | MIGRATE |
| #226 SemanticUtterancePlan | Characterより上流でspeech act/target/propositions/budgets/required/forbidden確定 | #362 | MIGRATE |
| #227 Character Language Realizer | raw internal valuesを再解釈せず確定意味をCharacter Profileで自然言語化 | #330 #355 | MIGRATE |
| #228 SpeechPerformancePlan | linguistic pauseとacoustic pauseを分離したengine-independent prosody | #331 #358 | MIGRATE |
| #229 Semantic / Realization Validator | Character speechをindependent semantic interpretationしtyped planと比較、finite matcher禁止 | #363 #352 #357 | MIGRATE |
| #235 Character設定親 | Human-readable人物像を正本にしLanguage/Voice/Bodyへ一貫投影 | #324 | MIGRATE |
| #236 Character Bible | Identity/Personality/Values/Social/Language/Voice/Bodyをuser確認しdynamic stateと分離 | #354 | MIGRATE |
| #237 CharacterProfile projection | Bible→Language/Voice/Body typed projections、Projectionを人物設定正本にしない | #355 | MIGRATE |
| #240 参考動画クラウド解析 | reference-only ASR/audio/visual、人間レビュー、素材直接再利用禁止 | #353 | TOOLING-MIGRATE |
| #288 有限自然語辞書全廃 | open-ended NL semantic authorityにkeyword/regex/substring/fallback禁止 | #326 #362 #330 #363 + system policy | MIGRATE |
| #290 Input Meaning唯一authority | raw user textのintent/negation/hypothetical/activity等をdownstream再解釈しない | #326 | MIGRATE |
| #291 Confirmation typed semantics | confirmationをphrase listで分類せずtyped result、low confidence実行禁止 | #326 #328 | MIGRATE |
| #292 Claim/Budget/Existence typed検証 | claim/question/topic/existenceをfinite regexでなくsemantic plan + actual facts + closed checks | #328 #362 #330 #363 | MIGRATE |
| #293 degree語辞書撤去 | intensity/certaintyをfinite vocabulary検出せずindependent semantic observation | #362 #330 #363 #357 | MIGRATE |
| #295 Issue graph | parent/dependency/Projects statusをread-only graph可視化 | #353 | TOOLING-MIGRATE |
| #303 Semantic Realization再構築 | proposition facets、Structured Outputs、relative semantic verifier、model baseline | #362 #330 #363 #357 #352 | MIGRATE |
| #311 ChatGPT全チャット議事録 | 開発経緯の歴史資料。current state authorityではない | #207 + history docs | HISTORY-RETAIN |
| #312 System Architecture Visualizer | AST/read-only architecture graph、search/filter/Render、production authorityなし | #353 | TOOLING-MIGRATE |
| #314 Resume Gate | summaryからstate確定禁止、live GitHub、Resume Certificate、multiple lineage STOP | #317運用全体 | OPS-RETAIN |

---

## 5. Initial Open PR migration

初回inventoryの23 PRはV2へmerge/cherry-pickせずrequirement/failure knowledgeだけ回収。

| PR | Live title | 回収するもの | V2 destination | Disposition |
|---|---|---|---|---|
| #130 | 内部指示器クラウド検証ラボ | production path Lab、fake/live、preset/export、existence boundary等 | #352、Executive知見→#328 | TOOLING-MIGRATE |
| #203 | Awakening Context / Persistence | cold/resume/restart、minimum snapshot、persistence failure非致命 | #327 #350 #359 | MIGRATE |
| #204 | Awakening Appraisal / Lifecycle | previous state直接復元せずAppraisal、停止時間減衰、固定Preset禁止 | #327 | MIGRATE |
| #205 | Awakening→Body/Autonomy因果統合 | high-level Body projection、Autonomy同一経路 | #337 #333 | MIGRATE |
| #206 | Awakening実HTTP/SSE統合 | real boundary、initial causal state、degradation | #352 #360 | MIGRATE |
| #219 | internal-state direct question | typed target、diagnostic label禁止、semantic consistency | #326 #327 #328 #362 #330 #363 | MIGRATE |
| #224 | Character / Validator Lab | Character/Validator production-path isolation Lab | #352 | TOOLING-MIGRATE |
| #230 | Character LLM言語実現専用化 | Semantics→Character→Performance分離、raw stateをCharacterへ渡さない | #362 #330 #331 #355 | MIGRATE |
| #231 | SemanticUtterancePlan | typed propositions/target/budget、What-to-sayをCharacterより上流へ | #362 | MIGRATE |
| #232 | Character Realizer移行 | narrow input、strict schema、TTS/Body責務除去 | #330 #357 | MIGRATE |
| #233 | Semantic / Realization Validator分離 | independent observation、typed comparison、certainty/intensity/unknown failure | #362 #330 #363 #357 | MIGRATE |
| #234 | Character Lab stack更新 | semantic Lab、regression、failure aggregation/export | #352 | TOOLING-MIGRATE |
| #238 | Character Bible初稿 | confirmed/unconfirmed分離、user未確認項目を確定扱いしない | #354 | MIGRATE |
| #241 | 参考動画クラウド解析 | reference-only、cloud ASR、result persistence、素材直接再利用禁止 | #353 | TOOLING-MIGRATE |
| #289 | 有限自然語辞書全廃 | NL lexical decision policy、semantic fallback禁止 | #326 #328 #362 #330 #363 | MIGRATE |
| #296 | Issue親子/進行graph | official parent/subIssue、Projects fields、Render/secret boundary | #353 | TOOLING-MIGRATE |
| #301 | CI-only semantic contract | certainty/optional realization failure regression evidence | #362 #330 #363 tests | CI-ARCHIVE |
| #302 | Semantic Realization再評価 | exact round-trip weakness、facets、Structured Output、relative verifier、model matrix | #362 #330 #363 #357 #352 | MIGRATE |
| #304 | Semantic Realization v2 | proposition/alignment/Structured Output design、codeは移植しない | #362 #330 #363 #357 | MIGRATE |
| #310 | Character Semantic model matrix Lab | Character/Verifier model独立評価、mini baseline、failure class | #352 #357 #363 | TOOLING-MIGRATE |
| #313 | module dependency visualizer | read-only AST graph、logical module、Render | #353 | TOOLING-MIGRATE |
| #315 | Resume Gate運用 | live GitHub authority、STOP、Certificate、Checkpoint、single lineage | #207 #314 / V2 ops | OPS-RETAIN |
| #316 | 全チャット議事録永続化 | why-history。current architecture authorityではない | history docs / #207 | HISTORY-RETAIN |

---

## 6. Cross-cutting user requirements

### R01 Speech playback中next generation — P0

前Speech playback + next LLM latencyを直列加算しない。

V2: #322 #323 #333 #348 #334 #360。

### R02 Free Body

360°、full-body、multiple simultaneous motion、current pose、no Home reset、jump、gaze/breath/viseme/micro-motion、Canonical 3D。

V2: #335〜#341 #346。

### R03 Multimodal input

TextだけでなくVoice/Vision/Touch/Streaming/Game等。Touchはpointer sampleとactual avatar hit/body regionを分離。

V2: #349→#326/#327。

### R04 General reference

「もう一回」「それ」「さっきの」をrecent speech/decision/**Goal**/Activity/Execution/Memoryからbounded typed解決。

V2: #326 #366 #329 #332。

### R05 Autonomous behavior from state/goal

fixed timer→fixed speechでなくInternal State、Interest、Relationship、Goal/Commitment、Activity、turn/focusからExecutive trigger。

V2: #327 #328 #366 #333 #348。

### R06 Internal state richness

Emotion、Desire、Drive、Motivation、Values/Moral appraisal、Interest/Curiosity、Relationship、Energy等をdynamic causal stateとしCharacter static traitと分離。

V2: #327 #354 #355。

### R07 Startup non-neutral

previous state / downtime / current contextをAppraisalしSpeech/Body/Silenceへ通常因果経路。

V2: #327 #333 #337 #350 #359。

### R08 Truthfulness / existence

unavailable senses/physical experienceや未実行行為を事実claimしない。

V2: #329 #366 #362 #330 #363 #354 #355。

### R09 Character / Body siblings

Character textからBody commandを作らずBody poseからSpeech意味を決めない。同じExecutiveからfan-out。

V2: #328 #362 #330 #338 #341。

### R10 Streaming independent

StreamingはCore PluginではなくSubsystem。comment burstをbounded/aggregatedにしCore cognitionをblockしない。

V2: #345 #347 #333。

### R11 GUI/Lab non-authority

production DTO/Port/read modelを利用しCore logicコピー禁止。

V2: #351 #352。

### R12 Module development gate

`Design → Unit → Adjacent → Integration → Verification`。全体起動を一次品質証明にしない。

V2: #317/#360/system architecture。

### R13 Free will vs Skill AI

Executiveが会話/配信/Game等のGoalを選び、専門Skill AIは選択済みActivityを実行する。

V2: #328 #361 #345 #347 #365 #360。

### R14 Persistent Goal / Commitment canonical state — P0

「やりたい」「あとでやる」「約束した」がLLM context windowとともに消える構造を禁止。

```text
Executive decision
→ validated Goal/Commitment transition
→ #366 persistent state
→ later Attention/Planner/Executive context
```

GoalとActivity、GoalとMemory、CommitmentとCharacter utteranceを分離する。

stale `goal_revision` Planを実行しない。

V2: #328 #366 #361 #329 #333 #334 #360 #359。

### R15 Bounded Attention / Focus for simultaneous activities — P0

Game、Streaming、Conversation、Reflection等の全Eventを同じpriorityでExecutiveへ無制限同期投入しない。

```text
Appraisal salience
+ Executive attention intent
+ turn/user priority
→ #333 AttentionFocusState / scheduling
→ eligible Executive triggers
```

Game frame/comment burstはSubsystem側aggregation + attention budgetを通す。

Attentionは意味/Goalを決めない。Body gazeはAttentionの表現でありcognitive Authorityではない。

V2: #327 #328 #333 #337 #340 #347 #365 #322 #360。

---

## 7. Legacy Failure Classes to Preserve

### Natural language

- finite marker/regex misses paraphrases
- lexical fallback destroys semantic authority
- unknown/certainty/intensity exact reconstruction from surface tokens causes false accept/reject

V2: #326 #362 #330 #363 #357。

### Character

- raw internal values cause target substitution / diagnostic speech
- Profile entering Fact Authority changes semantics

V2: #328 #362 #330 #355。

### Semantic verification

- Character self-asserted fidelity is not independent verification
- free-form validator final authority creates another decision authority
- finite markers fail on paraphrase

V2: #363 + closed acceptance, #352。

### LLM latency / topology

- separated LLM responsibilities chained serially add provider latency to critical path
- background cognition can starve foreground
- stale long-running result can corrupt current causal state

V2: #322 #323 #333 #348 #357 #360。

### Persistent intention

- Goal/Commitment held only in Prompt/conversation context disappears after turns/context truncation
- Activity state or Memory cannot substitute current Goal canonical state
- stale plan after Goal change can execute wrong action

V2: #366 #328 #361 #334 #360。

### Attention overload

- sending every Game frame/comment/sensor event to Executive causes queue explosion/latency
- no explicit focus owner makes Game/Streaming/User priority inconsistent
- attention represented only as Body gaze confuses expression with cognition

V2: #333 #322 #347 #365 #337/#340。

### Speech timing

playback completion before next generation creates playback duration + LLM latency gap.

V2: #348。

### Body

finite action preset、face-only movement、home reset、2D renderer constraint leakage block free motion。

V2: #336 #338 #339 #340 #341。

### Memory

raw conversation unconditional persistence、LLM free-text direct write、old Memory as current truth。

V2: #364 #332 #359。

### Shutdown

optional output disconnect error spam、Ctrl+C orphan task、external failure propagation。

V2: #322 #350。

### Validation

full runtime-only testing、test phrase→production dictionary patch、stronger model hiding architecture defects。

V2: #352 + Module Gate。

---

## 8. Legacy Closure Policy

Matrix存在だけでold Issue/PRを即closeしない。

```text
1. Matrix mapping
2. destination Issue existence
3. canonical consistency audit
4. cross-cutting requirements
5. #318 checkpoint
6. #317 Design Gate/user confirmation
7. old PR superseded comment
8. old implementation PR close unmerged
9. old Work/Parent close or retained classification
10. Project #6 V2 sync #319
```

#207/#314はoperations authorityとしてretain。history docsはhistoryとしてretain。

---

## 9. Completion

- [x] Legacy Open Issue 44 mapping
- [x] initial Open PR 23 mapping
- [x] Awakening / Conversation / Turn / Expression
- [x] Memory #364 vs #332
- [x] Input Meaning / finite lexical prohibition
- [x] Speech Semantics / Character / Verifier / Performance
- [x] Body freedom / IK / 3D / realtime
- [x] Touch / multimodal
- [x] Plugin structural definition / zero-plugin separation
- [x] Streaming independent Subsystem
- [x] Game Skill #365
- [x] persistent Goal / Commitment #366
- [x] bounded Attention / Focus #333
- [x] GUI/Lab/Tooling
- [x] graceful degradation/shutdown
- [x] Resume Gate / single lineage
- [x] playback中next generation P0
- [x] variable LLM / non-serial runtime
- [x] final cognitive destination reconciliation
- [ ] #318 final reconciliation checkpoint
- [ ] #317 final Design Gate/user confirmation
- [ ] confirmed後legacy implementation lineage superseded close
- [ ] #319 Projects v2 actual sync
