# AI Liver ゆら V2 Speech Pipeline Architecture

Status: Draft / V2 Design Gate
System: `docs/architecture/v2/system_architecture.md`
Brain: `docs/architecture/v2/brain_architecture.md`
Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Work Issue: #348
Root: #317

## 1. 目的

発話で次を同時に成立させる。

1. `What to say` と `How to say it` を分離。
2. Character発話の意味保持を独立観測可能にする。
3. 責務分離をLLMの固定数珠つなぎへ変換しない。
4. current Speech提示中でもnext cognition / speech preparationを進める。
5. staleな候補を無条件提示しない。

V1で得たsemantic fidelityの知見を維持しつつ、LLM/TTS/playback latencyを単純加算しない。

---

## 2. 禁止構造

### Playback直列化

```text
Speech A generate
→ TTS A
→ await A playback complete
→ next Appraisal / Executive
→ Speech B generation
```

禁止。

### LLM数珠つなぎ

```text
Executive
→ await Speech Semantics LLM
→ await Character LLM
→ await Verifier LLM
→ await Performance
→ await TTS
→ Presentation
```

を全Speechの固定critical pathにしない。

---

## 3. Logical Responsibilities

```text
Executive SpeechIntent
        ↓
Speech Semantics #362          What to say
        ↓
SpeechSemanticPlan
        ↓
Character Language #330        How to say it
        ↓
CharacterUtterance
        ↓
Semantic Verification #363     independent observation
        ↓
Closed typed acceptance
        ↓
Speech Performance #331
        ↓
PreparedSpeechCandidate
        ↓
Presentation commit / TTS / playback
```

Authority/data dependencyであり固定Runtime sequenceではない。

---

## 4. Authority

### Executive #328

発話する/しない、発話目的、優先度等の上位SpeechIntentを決める。最終台詞や詳細propositionを常時生成しない。

### Speech Semantics #362

`What to say` Authority。

```text
SpeechSemanticPlan
- speech_plan_id
- speech_act / target
- propositions[]
- required / optional / forbidden content
- polarity / certainty / degree
- self_disclosure
- question / new_direction budget
- execution_truth_constraints
```

### Character #330

`How to say it`。Characterらしさを加えるがPlanの意味・事実・certainty等を変更しない。

### Verifier #363

Observer。

`SpeechSemanticPlan + CharacterUtterance → SemanticRelationObservation`。

Speech Intent変更、Character直接指揮、Runtime Fact変更、free-form final Authorityを持たない。final accept/rejectはtyped observation + closed policy。

### Speech Performance #331

engine-independent prosody / pause / timing / acoustic intent。TTS固有parameterはProvider側。

### Presentation

外部へ実際に提示されたFactを所有。Prepared candidateは「話した」Factではない。

---

## 5. Sparse Activation

全Speechで全RoleをLLM起動しない。

### Simple Path

Executive SpeechIntentとtyped factsだけで内容が十分確定:

```text
Executive SpeechIntent
→ lightweight / deterministic semantic projection
→ SpeechSemanticPlan
→ Character
```

専用Speech Semantics LLMを省略可能。ただしPlan Contract / Authorityは維持。

### Complex Path

複数proposition、Memory evidence、self-disclosure、Relationship/discourse constraint等を統合する場合のみ専用Speech Semantics LLMを利用可能。

### Verifier Policy

- high semantic risk / complex semantics: verifier required
- low-riskでclosed deterministic contractが同等保証できるpath: explicit policyで省略可能

場当たり的skipは禁止。

---

## 6. Preparation / Presentation分離

```text
Preparation lane
  Speech Semantics / Character / Verifier / Performance
  optional speculative TTS
  → PreparedSpeechCandidate

Presentation lane
  pre-present revalidation
  → required acceptance gates
  → TTS/audio readiness
  → commit
  → text/audio playback + viseme
  → SpeechPresentationResult
```

Presentation完了を次Preparation開始条件にしない。

---

## 7. Parallelism

### Character completion後

```text
CharacterUtterance
├─ required Semantic Verifier
├─ Speech Performance
└─ speculative TTS prep (policy permitting)
```

required Verifier PASS前にexternal Presentation commitしない。
FAILならspeculative workを破棄。

### Executive fan-out

```text
ExecutiveDecision
├─ Speech preparation
└─ Body planning
```

Character completionをBody planningの開始条件にしない。Body completionもCharacter generationをblockしない。

---

## 8. Playback中のNext Preparation

```text
Speech A presenting
while
  new Event arrives
  Input Meaning / Appraisal / Attention may run
  Executive may decide
  Speech B semantics/Character may prepare
  Verifier B may run
  TTS B may prepare safely
```

A playback durationがB generation startへ直列加算されない。

B prepared ≠ B must be spoken。

---

## 9. PreparedSpeechCandidate

```text
PreparedSpeechCandidate
- candidate_id
- source_decision_id
- source_event_ids[]
- speech_plan_id
- source_context_revision
- goal_revision?
- attention_revision?
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

Lifecycle:

```text
preparing → prepared → queued → revalidating → ready_to_present
→ presenting → completed
or cancelled / superseded / stale / rejected / failed
```

---

## 10. Revalidation

Presentation直前に必要に応じ確認:

- source_context_revision
- goal_revision
- attention_revision / turn ownership
- new user input / stronger-priority event
- Goal / Commitment
- topic / discourse
- major Internal State change
- Capability / Execution Facts
- preconditions / expiry / cancellation

staleなら提示しない。

---

## 11. Interruption / Attention

#333のFocus/Turn stateを利用する。

Queued autonomous candidateはuser input / focus shiftでcancel / supersede / revalidate可能。

Current Speechはpriority / interruptibility / turn policyによりcontinue / soft finish / interrupt。

TTS Adapterは意味判断しない。

---

## 12. TTS / Body

TTS preparation policy:

- commit直前
- high-confidence candidateのみ先行
- verifierとparallel speculative prep

を選択可能。

実際にcommitされたSpeechだけをBody visemeへ渡す。

```text
Committed Speech
+ actual audio start
+ pronunciation / viseme timeline
→ Body Realtime
```

未commit候補で口を動かさない。
Body full motion / gaze / blink / breathはSpeech preparation待ちで停止しない。

---

## 13. Queue / Backpressure

future speechを無制限生成しない。

初期基準:
- presenting: max 1
- immediate prepared next: normally ~1
- unlimited future candidates: forbidden

pressure時:
- stale/low-priority discard
- same-intent coalesce
- generation suppression

foreground user responseをbackground autonomous candidateでstarveしない。

---

## 14. Latency / Observability

critical pathは論理責務全latencyの単純和ではない。

記録:

```text
event_received
executive queued/started/completed
speech semantics queued/started/completed
character queued/started/completed
verifier queued/started/completed
performance started/completed
tts prep started/completed
candidate prepared/revalidated
presentation started/completed
cancelled/stale/superseded
```

Role/workごと:
- queue wait
- provider latency
- priority
- source_context_revision
- goal_revision / attention_revision if relevant
- cancellation/stale outcome

指標:
- user input→Executive
- user input→first preparation
- user input→presentation
- previous playback中next generation start
- speech critical path
- speculative discard rate
- p50 / p95 / p99

---

## 15. Unit / Adjacent Acceptance

実装時にfake clock / fake LLM / fake TTSで最低限:

1. A playback 5s/20s中にB generation開始可能。
2. playback duration増加がB generation startへ同量加算されない。
3. simple no-Semantics-LLM path。
4. complex dedicated Semantics path。
5. slow Verifier中safe Performance/TTS prep parallel。
6. Verifier FAIL時speculative audio非提示。
7. slow TTS中new Event/Executive継続。
8. user input/focus changeでqueued autonomous candidate取消/再検証。
9. stale context/goal/attention revision非提示。
10. bounded queue / no call explosion。
11. Body realtime非block。
12. cancellation後pending taskなし。
13. Speech/Body sibling fan-out。
14. background candidateでforeground starvationなし。

Adjacent:
- Executive ↔ Speech Semantics
- Speech Semantics ↔ Character
- Character ↔ Verifier
- Verifier ↔ Presentation
- Speech ↔ Body
- Speech ↔ #333 Attention/Turn

---

## 16. V1からの教訓

維持:
- What-to-say / How-to-say分離
- independent semantic observation
- typed semantics
- finite lexical matcher非Authority
- Character責務過剰回避

改善:
- Role/Issue分離をserial API call数にしない
- playback完了をnext cognition gateにしない
- Verifierをfree-form final Authorityにしない
- safe prepでlatency overlap
- Goal/Attention revisionでstale candidateを閉じる

---

## 17. Design Reconciliation Status

設計として以下は反映済み。Runtime PASSは各Work/Integration実装後に別途検証する。

- [x] #362 Speech SemanticsをBrain hierarchyへ追加
- [x] #330 Character LanguageとWhat-to-say Authorityを分離
- [x] #363 VerifierをObserverとして定義
- [x] #348 Preparation / Presentation non-blocking設計
- [x] Runtime Kernel #322がpriority / cancellation / concurrent task contractを所有
- [x] simple / complex Speech path
- [x] required Verifierとsafe speculative preparationのparallel設計
- [x] playback中next-generation Acceptanceを#348/#352/#360へ配置
- [x] Role latency / queue wait / p95/p99 observabilityを#352/#360へ配置
- [x] playback durationがnext generation startをblockしないことをSystem Acceptanceへ配置
- [x] Role数/Issue数を固定serial API call数へ変換しない
- [x] Goal revision / Attention revisionをpre-presentation revalidationへ接続

残るのは実装後Unit/Integration/Live Verificationと#317全体Design Gate確認である。
