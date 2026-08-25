# V2 Speech Performance Contracts

Owner Issue: #331
Parent: #325
Upstream: #330, #355, #327, #328
Downstream: #348, #358, #340
Related:
- `docs/architecture/v2/speech_pipeline_architecture.md`
- `docs/architecture/v2/character_projection_contracts.md`
- `docs/architecture/v2/concurrency_architecture.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

#331 Speech Performanceは、**確定済みの言葉を変更せず、どう音声として演じるかをengine-independentに計画するRealizer**である。

```text
CharacterUtterance                # words / linguistic boundaries
+ CharacterVoiceStyleProfile      # static Character voice style
+ SpeechExpressionContext         # current dynamic expression projection
        ↓
Speech Performance Planner
        ↓
SpeechPerformancePlan             # engine-independent performance intent
        ↓
#348 Speech Pipeline
        ↓
#358 TTS Provider Adapter
        ↓
audio + pronunciation/timing
```

#331は発言意味、事実、Goal、Emotion正本、TTS provider parameter、actual audio timingを所有しない。

---

## 2. Authority boundary

### 2.1 Language Authority

#330 `CharacterUtterance`が言語表現のAuthorityである。

#331は次を変更しない。

- segment text
- segment順序
- realization refs
- question/new-direction budget
- proposition semantics
- polarity / certainty / degree / execution truth

Performance上の都合で単語を挿入・削除・言い換えしない。

発音上の読み替え・phoneme変換は#358のprovider/lexicon boundaryで扱い、表示/意味上のCharacterUtterance textを書き換えない。

### 2.2 Static Character Voice Style Authority

#355 `CharacterVoiceStyleProfile`がstatic Character voice tendencyのread-only Authorityである。

利用できるのは`RuntimeAvailability.CONFIRMED` facetだけ。

初期closed facet:
- `baseline_softness`
- `calmness_tendency`
- `emotional_expressiveness_tendency`
- `energy_tendency`
- `pacing_tendency`

Profile valueは高レベルStyle evidenceであり、VOICEVOX speaker ID、speed scale、pitch scale等のprovider値ではない。

### 2.3 Dynamic expression Authority

current Emotion / Desire / Drive等の正本は#327 Internal Stateであり、#331が状態を変更しない。

#331はcurrent stateを直接自由解釈する代わりに、bounded read-only `SpeechExpressionContext`を使う。

`SpeechExpressionContext`は#331のperformance入力用projectionであり、新しいEmotion/Goal Authorityではない。

入力Source:
- current #327 `InternalStateSnapshot`のrevision付きread-only evidence
- committed #328 Speech Intentに付随する高レベルperformance constraintが存在する場合、そのtyped reference
- current turn/situation上のperformance constraintが必要な場合、そのtrusted typed view

projectionはperformance軸だけを生成し、新しい発言内容を生成しない。

---

## 3. SpeechExpressionContext

```text
SpeechExpressionContext
- expression_context_id
- source_context_revision
- internal_state_revision
- attention_revision?
- source_refs[]
- activation
- energy
- softness
- tension
- warmth
- expressiveness
- pacing_bias
- emphasis_bias
- updated_at
```

各連続軸はnormalized scalarとする。

- signed tendency: `[-1.0, +1.0]`
- magnitude-only tendency: `[0.0, 1.0]`

boolを数値として受理しない。NaN/Infinityは禁止。

これらは「joyならpitch +0.2」等の固定Emotion presetではない。

projection policyは複数のcurrent State evidenceを合成できるが、次を禁止する。

- Emotion名 → 固定Speech presetの1対1辞書
- raw internal key/valueをTTSへ直接渡すこと
- Character Bibleのstatic traitからcurrent Emotionを捏造すること
- ExpressionContextからSpeech propositionを生成すること

`SpeechExpressionContext`が利用不能な場合はtyped degradedとして扱い、Characterに存在しない感情を補作しない。

---

## 4. Performance input snapshot

```text
SpeechPerformanceContextSnapshot
- performance_request_id
- utterance: CharacterUtterance
- voice_style: CharacterVoiceStyleProfile
- expression: SpeechExpressionContext?
- performance_constraints[]
- source_context_revision
- goal_revision?
- attention_revision?
- captured_at
- trace_id
```

### 4.1 Snapshot invariants

- `CharacterUtterance`は#330でcommit済み。
- semantic acceptanceの有無は#331の入力生成条件にしない。#363と#331はCharacter後にparallel開始可能。
- `voice_style.character_id/schema_version/definition_revision`はCharacterUtteranceのCharacter provenanceと一致する。
- raw user text / raw conversation history / provider SDK objectを含めない。
- current Internal State objectをmutable aliasで保持しない。

### 4.2 Performance constraints

必要な場合だけbounded `SpeechPerformanceConstraintView`を渡す。

```text
SpeechPerformanceConstraintView
- constraint_id
- source_owner
- source_ref
- source_revision
- kind
- value
```

例:
- explicit quiet-delivery requirement
- external environment volume limitation
- presentation accessibility constraint

constraint ID文字列を意味として解析しない。

---

## 5. SpeechPerformancePlan

```text
SpeechPerformancePlan
- performance_plan_id
- utterance_id
- source_decision_id
- source_event_ids[]
- revisions
- character_id
- character_schema_version
- character_definition_revision
- expression_context_id?
- global_intent: PerformanceIntentVector
- segments[]: SpeechPerformanceSegment
- degraded
- degradation_reasons[]
- created_at
```

Planはimmutable derived dataである。

`SpeechPerformancePlan`生成成功は:

> 言語を変更せず、現在入力されたVoice Style / Expression evidenceに基づくengine-independent performance intentを構成できた。

ことだけを意味する。

これは:
- #363 semantic acceptance
- TTS synthesis success
- Presentation commit
- actual speech started/completed

を意味しない。

---

## 6. PerformanceIntentVector

Provider数値ではなく相対的・normalizedな演技意図を表す。

```text
PerformanceIntentVector
- pace
- energy
- pitch_center
- pitch_range
- loudness
- softness
- breathiness
- tension
- expressiveness
```

基本範囲は`[-1.0, +1.0]`とし、0はsystem-neutral relative pointである。

重要:
- 0を「ゆらの人格上neutral」とは扱わない。
- providerのspeed/pitch/volume numerical scaleとは一致しない。
- #358がProvider capability/rangeへ変換する。
- provider capability不足で#331のsemantic/performance plan自体を書き換えない。

CharacterVoiceStyleProfileはbaseline tendencyとして作用し、SpeechExpressionContextはcurrent modulationとして作用する。

```text
static voice tendency
+ current expression modulation
+ bounded performance constraints
→ normalized performance intent
```

合成はbounded/deterministicとし、特定Emotion名に対する固定preset selectionを正規方式にしない。

---

## 7. Segment performance

#330の各`CharacterUtteranceSegment`へexactly oneの`SpeechPerformanceSegment`を対応させる。

```text
SpeechPerformanceSegment
- performance_segment_id
- utterance_segment_id
- boundary_strength
- pause_after_intent
- duration_bias
- emphasis_strength
- hesitation_strength
- local_intent_delta
- pitch_anchors[]
```

segment textは複製せず`utterance_segment_id`で参照する。

### 7.1 Boundary / pause

#330 `boundary_after`:
- CONTINUE
- PHRASE
- SENTENCE

はlinguistic structureである。

#331はこれを、Expression/Voice Style/contextを考慮したrelative `boundary_strength / pause_after_intent`へ投影する。

実秒数は決めない。

### 7.2 Emphasis

#330 `emphasis`を最低限の言語的constraintとして尊重する。

- EMPHASIZEDを0強度へ潰さない。
- DEEMPHASIZEDを過度な強調へ反転しない。

ただしactual pitch/volume値へ1対1固定変換しない。

### 7.3 Hesitation

#330 `hesitation=HESITANT`は言語上のhesitation evidenceである。

#331はpause/duration/energy等の演技意図へ反映可能だが、固定fill wordを追加しない。

### 7.4 Pitch anchors

必要な場合はengine-independentな相対contourを表す。

```text
PitchAnchor
- position       # segment内normalized 0..1
- relative_pitch # -1..+1
- strength       # 0..1
```

providerがcontour制御を持たない場合、#358がdegraded mappingする。

`PitchAnchor`は日本語アクセント辞書・phoneme timingの代替ではない。実発音/timingは#358。

---

## 8. Static style + dynamic expression composition

### 8.1 Character style

CharacterVoiceStyleProfileは「普段どういう傾向か」を示す。

### 8.2 Current expression

SpeechExpressionContextは「今の状態が演技にどう反映され得るか」を示す。

### 8.3 Result

最終Performanceは両者の合成結果であり、どちらか片方へ固定しない。

例:
- baselineは比較的soft/calm
- strong current activationではenergy/expressivenessが上がり得る

ただし「joy→必ず高音」「fear→必ず早口」等をcanonical ruleにしない。

同一Emotion stateでもSituation、Speech segment、Voice StyleによりPerformance結果が異なり得る。

---

## 9. Deterministic planning responsibility

初期#331のcanonical plannerはdeterministic projection / compositionを基本とする。

理由:
- Word/meaningは#330までで確定済み。
- Voice StyleとExpressionは既にtyped evidence。
- engine-independent intent compositionはclosed normalized spaceで表現できる。
- Speech Performanceのために追加LLMを毎発話のcritical pathへ必須化しない。

将来learned/LLM performance modelを導入する場合も:
- logical #331 Authorityは維持
- outputは同じtyped candidate/commit gateへ通す
- provider-specific parameterやtext rewriteを許可しない
- playback critical pathへ無条件追加しない

という別Design Gateを必要とする。

---

## 10. Validation / commit

`SpeechPerformancePlanner.plan()`はpure/short-runningであることを基本とする。

最低限検証:
- utterance/profile Character provenance一致
- segment mapping exactly one-to-one
- unknown utterance segment ref reject
- normalized numeric bounds
- duplicate segment mapping reject
- pitch anchor position ordering/bounds
- Character words/text non-mutation
- current snapshot identity/revision consistency

commit後のPlanはimmutable。

#331はPresentation queueやactual audio stateをmutationしない。

---

## 11. Freshness / rebind policy

Speech Performanceはcurrent expressionの影響を受けるため、PreparationからPresentationまでの長い遅延では再評価が必要になり得る。

#331は次をprovenanceとして保持する。

- source_context_revision
- goal_revision if applicable
- attention_revision if applicable
- internal_state_revision via expression context
- Character definition revision

Presentation直前のstale/rebind Authorityは#348が所有する。

### Hard stale candidate

少なくとも:
- CharacterUtterance自体がsuperseded/rejected
- Character definition revisionがincompatibleに変化
- source Speech candidateがcancelled

では旧Performanceを提示しない。

### Rebindable expression drift

Internal State / expression revisionの通常変化だけなら、Speech textを捨てる必要はない場合がある。

#348はpolicyに応じ:

```text
same accepted CharacterUtterance
+ latest SpeechExpressionContext
→ #331 performance re-plan
→ TTS reprepare if needed
```

を行える。

すでにexternal Presentationが開始済みなら、過去Performanceを「なかったこと」にせずActual Presentation Factを維持する。

---

## 12. Concurrency

- #331は#363 verifier completionを待たずに開始できる。
- #363 required PASS前にexternal Presentation commitはしない。
- previous Speech playback中でもnext #331 planning可能。
- #331計画待ちをBody realtimeのblocking prerequisiteにしない。
- global Speech Performance lockを持たない。
- separate utterance candidatesは独立計画可能。
- current expression readはbounded immutable snapshotとする。

#331がslow external I/Oを行わない設計とし、TTS I/Oは#358へ分離する。

---

## 13. Degradation

### Voice Style unavailable

CharacterVoiceStyleProfileが利用不能/invalidの場合:
- Character styleを推測しない。
- `degraded=true` + `CHARACTER_VOICE_STYLE_UNAVAILABLE`を記録。
- policyで許可される場合のみsystem-neutral relative performance intentを生成する。

system-neutralはCharacter factではない。

### Expression unavailable

- current Emotionを推測しない。
- confirmed Character Voice Styleだけでbaseline performanceを構成可能。
- `EXPRESSION_CONTEXT_UNAVAILABLE`をdegradation reasonへ記録。

### Provider capability unavailable

#331はdesired engine-independent planを保持する。

Provider capabilityへの縮退は#358が所有する。
#331でVOICEVOX固有制約に合わせてcanonical planを削らない。

---

## 14. #358 TTS boundary

#358は:

```text
SpeechPerformancePlan
+ CharacterUtterance text
+ TTS capability / voice configuration
→ provider-specific request
→ audio / pronunciation timeline / timing
```

を所有する。

#358が返すresultには:
- applied performance dimensions
- degraded/unsupported dimensions
- actual audio reference
- available pronunciation/phoneme/viseme timing

を含められる。

#331はspeaker ID、VOICEVOX style ID、provider speed/pitch/intonation scaleを持たない。

---

## 15. #340 Body / Viseme boundary

#331がmouth shape/per-frame visemeを生成しない。

```text
#358 actual synthesis timing / pronunciation
→ committed Presentation timing
→ #340 Body Realtime
```

未commitのprepared speechで口を動かさない。

Speech expressionとBody expressionは同じcurrent stateから別Realizerとして派生できるが、互いの出力をAuthorityにしない。

---

## 16. Observability

最低限trace:

```text
performance_context_captured
performance_plan_started
performance_plan_completed
performance_degraded
performance_replanned
performance_cancelled_or_superseded
```

記録可能:
- performance_request_id / plan_id
- utterance_id
- character definition revision
- expression context revision
- source/goal/attention revisions
- duration
- degradation reason codes

記録禁止:
- secret
- provider raw response
- unbounded conversation text
- raw Internal State dumpを診断目的で無制限複製

---

## 17. Required tests

### Contract
- valid CharacterUtterance→PerformancePlan
- Character provenance mismatch reject
- exact one-to-one segment mapping
- unknown/duplicate segment mapping reject
- normalized range validation
- bool-as-number / NaN / Infinity reject
- pitch anchor ordering/bounds

### Authority
- segment textを変更できない
- Performanceがnew semantic propositionを追加しない
- Voice Style candidate/unknownをconfirmedとして利用しない
- raw Emotion名→fixed preset dictionaryを正規Authorityにしない
- provider parameterをDomain planへ持ち込まない

### Expression / Character
- same text + different confirmed Voice StyleでPerformance intent差
- same text/style + different SpeechExpressionContextでPerformance intent差
- unavailable expressionでcurrent emotionを捏造しない
- unavailable Character Voice Styleでtyped degradation

### Boundary
- linguistic PHRASE/SENTENCE boundaryがrelative pause intentへ投影される
- emphasized/deemphasized semanticsを反転しない
- hesitationでfixed filler wordを追加しない

### Concurrency / freshness
- verifier slowでもPerformance planning開始可能
- previous playback中next Performance planning可能
- normal expression revision driftをre-plan可能
- superseded CharacterUtteranceのPlanをPresentationへ通さない
- cancellation後pending taskなし

### Adjacent
- #330 CharacterUtterance→#331
- #331→#348 PreparedSpeechCandidate
- #331→#358 fake TTS mapping
- #358 timing→#340 viseme input

---

## 18. Non-goals

- Character text生成/修正
- semantic verification
- Speech queue / Presentation lifecycle
- provider-specific synthesis parameter決定
- pronunciation dictionary / phoneme generation
- actual audio duration predictionを正本化
- Body gesture/motion generation
- current Emotion/Goalのmutation
- fixed Emotion→Voice preset library

---

## 19. Design Gate

#331 implementation開始条件:
- 本文書が#331 canonical supplementとして確定
- #330 CharacterUtterance contractと型境界整合
- #355 CharacterVoiceStyleProfileとのfacet/provenance整合
- #348 Presentation/Freshness責務と整合
- #358 provider degradation責務と整合
- #340 viseme/timing責務と整合
- #445 Design Completion Gateが最終PASS

#331単独のDesign Gateが完了しても、#445 PASS前にproduction implementationへ移らない。
