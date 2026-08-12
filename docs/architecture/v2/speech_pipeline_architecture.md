# AI Liver ゆら V2 Speech Pipeline Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Brain architecture: `docs/architecture/v2/brain_architecture.md`
Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Work Issue: #348
Root management: #317

## 1. 目的

この文書は、ゆらの発話について次を同時に成立させる。

1. `What to say` と `How to say it` を責務分離する。
2. Character発話の意味保持を独立検証可能にする。
3. 責務分離をそのままLLMの数珠つなぎへ変換しない。
4. 現在Speechの提示・再生中でも次の認知・発話準備を進められる。
5. 古い文脈から生成された候補を無条件に提示しない。

V1で得た意味保持設計を維持しつつ、LLM latencyの単純加算を避ける。

---

# 2. 禁止する構造

## 2.1 Playback直列化

```text
Speech A生成
→ TTS A生成
→ A playback完了までawait
→ 次Appraisal
→ 次Executive
→ Speech B生成
```

禁止。

## 2.2 LLM数珠つなぎ

通常発話を常に次のように処理することも禁止する。

```text
Executive
→ await Speech Semantics LLM
→ await Character LLM
→ await Semantic Verifier LLM
→ await Speech Performance
→ await TTS
→ presentation
```

論理責務は分離するが、各責務が常に別の大型LLM API callとしてcritical pathへ直列加算される構造にはしない。

---

# 3. Speech logical responsibilities

```text
Executive SpeechIntent
        ↓
Speech Semantics
  What to say
        ↓
SpeechSemanticPlan
        ↓
Character Language Realization
  How to say it
        ↓
CharacterUtterance
        ↓
Independent Semantic Observation
        ↓
Closed typed acceptance policy
        ↓
Speech Performance
        ↓
PreparedSpeechCandidate
        ↓
Presentation commit / TTS / playback
```

この図はAuthority / data dependencyを表す。固定Runtime call sequenceではない。

---

# 4. Authority

## 4.1 Executive

「発話する／しない」「何のために発話するか」の上位Intentを決める。

Executiveは最終台詞を作らない。

## 4.2 Speech Semantics

Issue: #362

`What to say`を所有する。

```text
SpeechSemanticPlan
- speech_plan_id
- speech_act
- target
- propositions[]
- required_content[]
- optional_content[]
- forbidden_content[]
- polarity / certainty / degree facets
- self_disclosure
- question_budget
- new_direction_budget
- execution_truth_constraints
```

Character Profileは事実決定Authorityではない。

## 4.3 Character Language Realizer

Issue: #330

`How to say it`を所有する。

Characterらしさを加えるが、SpeechSemanticPlanの事実・polarity・certainty・degree・execution truth等を変更しない。

## 4.4 Independent Semantic Verification

Issue: #363

CharacterUtteranceがSpeechSemanticPlanを保持しているかをObserverとして評価する。

Verifierは最終発言Intentを変更しない。

Verifierのfree-form `accepted/reason`を最終Authorityにしない。Runtimeはtyped observationとclosed checksからaccept/rejectを導出する。

## 4.5 Speech Performance

Issue: #331

engine-independentな音響演技計画を所有する。

Character Language LLMにVOICEVOX等の具体parameterを生成させない。

## 4.6 Presentation Executor

実際に外部へ提示された事実を所有する。

Prepared candidateは「話した」という事実ではない。

---

# 5. Sparse speech path

すべての発話で全RoleをLLM起動しない。

## 5.1 Simple path

ExecutiveのSpeechIntentとtyped factsだけで十分に発言内容が確定できる低複雑度ケースでは、専用Speech Semantics LLMを省略できる。

```text
Executive SpeechIntent
→ lightweight / deterministic semantic projection
→ SpeechSemanticPlan
→ Character
```

例:

- 短いacknowledgement
- 型付きExecution Resultへの短い反応
- 既に意味内容が完全に確定した単純回答

省略はAuthority混同を意味しない。`SpeechSemanticPlan` contractは維持する。

## 5.2 Complex path

複数proposition、曖昧な自己開示、Memory evidence、Relationship / discourse constraint等を統合する必要がある場合のみSpeech Semantics LLMを起動できる。

```text
Executive SpeechIntent
→ Speech Semantics LLM
→ SpeechSemanticPlan
→ Character
```

## 5.3 Verifier activation

Verifierも「LLMがあるから毎回必ず呼ぶ」としない。

semantic risk / required assurance / path policyをtypedに定義する。

- high-risk / complex semantics: verifier required
- low-riskでclosed deterministic contractが同等保証できるpath: verifier省略を許可可能

省略条件は明示Policyとして検証し、場当たり的にskipしない。

---

# 6. Preparation / Presentation分離

```text
┌──────────────────────────────────────────────────────┐
│ Preparation domain                                   │
│                                                      │
│ Executive / Speech Semantics / Character / Verifier  │
│ Performance / optional speculative TTS preparation   │
│                                                      │
│ → PreparedSpeechCandidate                            │
└──────────────────────┬───────────────────────────────┘
                       │ bounded candidate state
                       ▼
┌──────────────────────────────────────────────────────┐
│ Presentation domain                                  │
│                                                      │
│ pre-present revalidation                             │
│ → required acceptance gates                          │
│ → TTS/audio readiness                                │
│ → presentation commit                                │
│ → text/audio playback + viseme                       │
│ → SpeechPresentationResult                           │
└──────────────────────────────────────────────────────┘
```

Presentation完了は次Preparation開始条件ではない。

---

# 7. Parallelism inside speech preparation

論理依存を壊さない範囲で並行化する。

## 7.1 Character完了後

Verifierが必要な場合:

```text
CharacterUtterance
├─ Semantic Verifier
├─ Speech Performance preparation
└─ speculative TTS preparation (policy permitting)
```

外部Presentation commitは必要なVerifier PASS前に行わない。

Verifier FAIL時はspeculative audio等を破棄する。

これによりVerifier latencyとTTS latencyを単純加算しない。

## 7.2 Executive fan-out

同一ExecutiveDecisionにSpeechIntentとBodyIntentがある場合:

```text
ExecutiveDecision
├─ Speech preparation
└─ Body planning
```

Character completionをBody planningの開始条件にしない。
Body completionをCharacter generationの開始条件にしない。

---

# 8. Speech A再生中のSpeech B準備

```text
Speech A presenting
while
  new Event may arrive
  Input Meaning may run
  Appraisal may run
  Executive may decide
  Speech B semantics may be prepared
  Character B may be generated
  Verifier B may run
  TTS B may be prepared speculatively
```

Aの再生時間がBのgeneration startへ直列加算されてはならない。

ただし「Bを準備できる」と「Bを必ず喋る」は別。

---

# 9. PreparedSpeechCandidate

```text
PreparedSpeechCandidate
- candidate_id
- source_decision_id
- source_event_ids[]
- speech_plan_id
- source_context_revision
- created_at
- priority
- interruptibility
- expiry_policy
- required_preconditions[]
- invalidation_keys[]
- semantic_acceptance_state
- CharacterUtterance
- SpeechPerformancePlan
- optional prepared_audio_ref
```

queueにあるだけではPresentation事実にならない。

---

# 10. Candidate lifecycle

```text
preparing
→ prepared
→ queued
→ revalidating
→ ready_to_present
→ presenting
→ completed

or
→ cancelled
→ superseded
→ stale
→ rejected
→ failed
```

Semantic verifier lifecycleとPresentation lifecycleを混同しない。

---

# 11. Pre-presentation revalidation

commit直前に最低限確認する。

- source_context_revision
- turn ownership
- new user input
- stronger-priority event
- current goal / commitment
- topic / discourse validity
- major state change
- capability / execution facts
- candidate preconditions
- expiry
- cancellation / supersede

古い候補は再生しない。

意味再判断が必要なら、新しいAppraisal / Executive / Speech preparationへ戻す。

---

# 12. User interruption

## 12.1 Queued autonomous candidate

user input arrival時に原則再評価する。

```text
queued autonomous candidate
+ user input
→ cancel / supersede / revalidate
```

機械的にqueueを消化しない。

## 12.2 Currently presenting speech

interruptibility / priority / turn stateに従い:

- continue
- soft finish
- interrupt

TTS Adapter自身が意味判断しない。

---

# 13. TTS policy

TTS準備タイミングはpolicy化する。

- commit直前までTTSしない
- high-confidence candidateだけ先行TTS
- verifierと並行してspeculative TTS

考慮:

- provider latency
- cost
- rate limits
- candidate invalidation率
- privacy / cache policy

TTS policyがSpeech意味を変更してはならない。

---

# 14. Body / viseme

実際にcommitされたSpeechだけをspeech/viseme realtime layerへ渡す。

```text
Committed Speech
+ actual audio start
+ pronunciation / viseme timeline
→ Body Realtime Layer
```

未commit候補で口を動かさない。

Body full-motion / gaze / blink / breathingはTTS / verifier / playback待ちで停止しない。

---

# 15. Queue / backpressure

future speechを無制限生成しない。

初期基準:

- presenting: 最大1
- immediately prepared next: 通常1程度
- unlimited future candidates: 禁止

queue pressure時:

- low priority candidate discard / supersede
- duplicate intent coalesce
- stale candidate drop
- new LLM call suppression

foreground user responseをbackground autonomous speech候補でstarveしない。

---

# 16. Latency model

`logical responsibility latency`と`critical path latency`を分けて観測する。

直列加算を最小化する。

```text
critical_path
!= meaning_latency
 + appraisal_latency
 + executive_latency
 + semantic_latency
 + character_latency
 + verifier_latency
 + tts_latency
 + playback_duration
```

必要な依存だけcritical pathに載せ、その他は並行 / deferred / speculative / optionalとする。

---

# 17. Observability

最低時刻:

```text
event_received_at
executive_started_at / completed_at
speech_semantics_queued_at / started_at / completed_at
character_queued_at / started_at / completed_at
verifier_queued_at / started_at / completed_at
performance_started_at / completed_at
tts_prepare_started_at / completed_at
candidate_prepared_at
candidate_revalidated_at
presentation_started_at / completed_at
candidate_cancelled_at / stale_at / superseded_at
```

各Role:

- queue wait
- provider latency
- source_context_revision
- priority
- cancellation / stale outcome

指標:

```text
user_input_to_first_preparation
user_input_to_presentation
previous_playback_to_next_generation_start
speech_role_critical_path
speculative_work_discard_rate
p50 / p95 / p99
```

---

# 18. Unit Acceptance

fake clock / fake LLM / fake TTSで最低限:

1. A playback 5s中にB generation開始・完了可能。
2. A playback 20sでもB generation startが20s後へ押し出されない。
3. simple speechで専用Speech Semantics LLMを省略できる。
4. complex speechでSpeech Semantics LLMを利用できる。
5. required Verifierが遅くてもSpeech Performance / policy許可されたTTS prepを並行可能。
6. Verifier FAIL時にspeculative audioをPresentationしない。
7. slow TTS中もnew Event / Executive workが進む。
8. user inputでqueued autonomous candidateをcancel / supersede可能。
9. context revision changeでcandidateをstale扱いできる。
10. queue upper boundを越えたLLM生成増殖がない。
11. Body/viseme処理がBrain preparationをblockしない。
12. cancellation時pending taskなし。
13. CharacterとBody planningを兄弟として並列開始可能。
14. background autonomous preparationがforeground user responseをstarveしない。

---

# 19. Adjacent Contract Acceptance

## Executive ↔ Speech Semantics

- SpeechIntentとSpeechSemanticPlanを混同しない。
- simple path / complex pathをtyped policyで選択可能。

## Speech Semantics ↔ Character

- What to say / How to say itが分離。
- Characterがsemantic authorityを奪わない。

## Character ↔ Verifier

- VerifierはObserver。
- free-form verdictを最終authorityにしない。

## Verifier ↔ Presentation

- required gate PASS前にexternal commitしない。
- safe speculative preparationは可能。

## Speech Pipeline ↔ Body

- commit Speechだけviseme対象。
- Body realtimeはSpeech preparation待ちにしない。

## Speech Pipeline ↔ Turn / Autonomy

- preparing / prepared / queued / presenting / completed / staleをtyped factとして参照可能。

---

# 20. Integration Verification

実LLM + 実TTSで時間軸を必ず確認する。

PASS例:

```text
Speech A presentation start    10:00:00.000
Speech B semantics start       10:00:00.700
Speech B character start       10:00:02.000
Speech B verifier start        10:00:03.600
Speech B TTS prep start        10:00:03.650
Speech A presentation end      10:00:08.000
Speech B revalidated           10:00:08.050
Speech B presentation start    10:00:08.300
```

FAIL例:

```text
Speech A presentation end      10:00:08.000
Speech B semantics start       10:00:08.010
Speech B character start       10:00:10.000
Speech B verifier start        10:00:12.000
Speech B TTS start             10:00:14.000
Speech B presentation start    10:00:17.000
```

前Speech完了後に全LLMを順番に開始しているためFAIL。

---

# 21. 非目標

- 必ず休みなく喋る
- 発話間隔0秒固定
- future speech大量先読み
- user input無視のqueue消化
- latency隠蔽用固定フィラー
- verifierをなくすこと自体を目標化
- LLM call数を増やすこと自体を目標化
- TTS audio無制限cache
- Presentation順序をCharacter LLMへ判断させる

目標は、**責務の明確さを保ったまま、必要なLLM latencyだけをcritical pathへ載せること**である。

---

# 22. V2 Design Gate条件

- [ ] #362 Speech SemanticsがBrain hierarchyに含まれる
- [ ] #330 Character LanguageとWhat-to-say authorityが分離
- [ ] #363 VerifierがObserverとして定義される
- [ ] #348がPreparation / Presentationを非block化
- [ ] Runtime Kernel #322がRole別Task / priority / cancellationを支援
- [ ] simple / complex speech pathが設計される
- [ ] required Verifierとsafe speculative prepを並列化可能
- [ ] playback中next-generation testがある
- [ ] Role latency / queue wait / p95/p99を観測できる
- [ ] playback durationがnext generation startをblockしない
- [ ] LLM Role数やIssue数が固定直列API call数へ変換されていない
