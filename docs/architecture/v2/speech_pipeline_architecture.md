# AI Liver ゆら V2 Speech Pipeline Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Work Issue: #348
Root management: #317

## 1. 目的

この文書は、ゆらの発話について**「内容を考える処理」と「実際に提示・再生する処理」を分離し、現在の発話再生中でも次の発話候補生成が進められること**をV2の構造的不変条件として固定する。

この要求は単なる低遅延最適化ではない。発話と発話の間が不自然に長くならず、ゆらが会話・自律行動を連続的に行えるための基本設計である。

禁止する正規構造:

```text
Speech Aを生成
→ TTS Aを生成
→ Speech Aの再生完了までawait
→ 再生完了後に次Appraisal
→ 次Commander
→ Speech Bを生成開始
```

この構造ではSpeech Aの再生時間がそのままSpeech Bの生成開始遅延へ加算される。V2では採用しない。

---

# 2. 最上位不変条件

1. **Speech playbackはBrain decision loopをblockしない。**
2. **現在Speechの再生完了を、次のAppraisal / Commander / Character generation開始条件にしない。**
3. **先行生成した発話候補は、再生直前に最新状態で再検証する。**
4. **先行生成はboundedであり、未来の会話を無制限に作り置きしない。**
5. **ユーザー入力・重要Event・内部状態変化で古くなった候補を破棄または再生成できる。**
6. **生成できることと、連続して発話してよいことを分離する。**
7. **TTS生成・audio playback・Body/viseme同期はPresentation側の実行責務であり、Character/Commanderの意思決定を待たせない。**
8. **発話中にもCoreはEventを受け取り、AppraisalとCommanderを進められる。**

---

# 3. 2レーン構造

```text
┌─────────────────────────────────────────────────────────────┐
│ Decision / Preparation Lane                                 │
│                                                             │
│ Event / Timer / State change                                │
│   ↓                                                         │
│ Appraisal                                                   │
│   ↓                                                         │
│ Commander                                                   │
│   ↓ SpeechIntent                                            │
│ Character Speech LLM                                        │
│   ↓ CharacterUtterance                                      │
│ Independent Semantic Verification                           │
│   ↓                                                         │
│ Speech Performance Planning                                 │
│   ↓                                                         │
│ PreparedSpeechCandidate                                     │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
                 bounded Prepared Queue
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Presentation / Execution Lane                               │
│                                                             │
│ Pre-play Revalidation                                       │
│   ↓                                                         │
│ TTS Preparation / Audio readiness                           │
│   ↓                                                         │
│ Presentation Commit                                         │
│   ↓                                                         │
│ Text / Audio Playback + Body / Viseme Sync                  │
│   ↓                                                         │
│ SpeechPresentationResult                                    │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            └────────→ Event / Appraisal feedback
```

重要なのは、**Decision LaneがPresentation Laneの完了を待たない**ことである。

Speech Aが再生中でも、Autonomy / Turn ManagementとCommanderが「次の発話候補を準備してよい」と判断した場合はSpeech BのCharacter生成を開始できる。

---

# 4. 責務境界

## 4.1 Appraisal

発話再生中という事実を含む現在状態を評価する。

例:

- currently_presenting_speech
- current speech interruptibility
- turn ownership
- user response obligation
- current topic
- internal motivation
- recent execution results
- pending prepared candidate count

Appraisalは「次を必ず喋る」と決めない。

## 4.2 Commander

次の候補を生成するか、待つか、沈黙するか、別Activityへ移るかを決める。

Commanderは次を区別する。

- `prepare_speech`: 内容候補を準備してよい
- `commit_speech`: Presentationへ出してよい
- `wait/silence`
- `cancel/supersede prepared speech`

実装上これらが別Command/phaseになるかはContract設計時に確定するが、**準備と提示の権威を同一時点に固定しない**。

## 4.3 Character Speech

Commanderが確定したSpeech semantic intentからCharacterUtteranceを作る。

現在別Speechが再生中であること自体を理由に生成を停止しない。

ただし、Characterへ「再生待ちqueueがあるから適当に続きの話を作る」権限は与えない。

## 4.4 Speech Performance

CharacterUtteranceから音声演技計画を生成する。

これもaudio playback完了を待つ必要はない。

## 4.5 TTS Adapter

TTSは可能なら先行準備できる。

ただし、TTS生成コスト・provider rate limit・候補失効率を考慮し、次のpolicyを選択可能にする。

- text/characterまで先行し、TTSはcommit直前
- TTSまで先行する
- 高優先度候補だけTTS先行

このpolicyはInfrastructure/Runtime policyであり、発話意味を変更しない。

## 4.6 Presentation Executor

実際のText/audio/Body speech syncを所有する。

Presentation Executorは再生中でもDecision Laneをlockしない。

---

# 5. PreparedSpeechCandidate

最低限以下を保持する。

```text
PreparedSpeechCandidate
- candidate_id
- source_command_id
- source_event_id?
- semantic_revision
- context_revision
- created_at
- priority
- interruptibility
- expiry_policy
- CharacterUtterance
- SpeechPerformancePlan
- optional prepared_audio_ref
- required_preconditions
- invalidation_keys
```

`context_revision`は、候補がどの状態を前提に生成されたかを識別するために使う。

候補がqueueにあることは「発話が確定した」ことを意味しない。

---

# 6. Speech Presentation Lifecycle

```text
prepared
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

`prepared/queued`と`presenting/completed`を明確に分離する。

Characterが「今言った」「今話している」等のexecution claimを行う場合はPresentation lifecycleの事実に従う。

---

# 7. Pre-play Revalidation

先行生成の最大の危険は、生成後に状況が変わっても古い発話をそのまま流してしまうことである。

そのためPresentation commit直前に最低限次を再検証する。

- candidate semantic revisionが現行会話文脈と互換か
- turn ownership
- 新しいユーザー入力の有無
- stronger-priority Eventの有無
- current Emotion/Motivationの重大な変化
- selected topicの有効性
- capability / execution factsの変化
- candidate preconditions
- candidate expiry
- cancellation / supersede flag

再検証で不整合なら、候補は`stale / superseded / cancelled`として再生しない。

---

# 8. ユーザー入力との競合

## 8.1 未再生自律候補

ユーザー入力が到着した場合、queue中の自律候補は原則として再評価対象とする。

通常は次のいずれかになる。

```text
queued autonomous candidate
+ user input
→ cancel
or
→ supersede
or
→ preserve only if still contextually valid and Commander explicitly re-commits
```

## 8.2 現在再生中Speech

現在再生中Speechは、内容・優先度・interruptibilityにより次を判断する。

- continue
- soft finish
- interrupt/cancel

この判断はTTS AdapterではなくCommander/Turn Management側のauthorityに従う。

---

# 9. 自律発話での先行生成

自律発話では、Speech Aを再生中にSpeech Bを準備できる。

ただし次を禁止する。

```text
自律開始
→ 未来3発話をまとめて固定生成
→ queue順に必ず全部再生
```

これは会話状態変化を無視するため採用しない。

正規形:

```text
Speech A presenting
→ current state / motivation / turn factsを継続評価
→ Commanderが次候補準備を許可
→ Speech B prepared
→ A presenting中もEvent処理継続
→ A完了付近/必要時にBをrevalidate
→ 最新状態でcommitできる場合のみBをpresent
```

「次発話を先に生成する」と「次発話を必ず行う」は別である。

---

# 10. 発話間隔の扱い

発話間隔を固定sleep値で作らない。

間隔は少なくとも以下の結果として決まる。

- current turn ownership
- discourse completion
- user response expectation
- Motivation / talkativeness
- interruption sensitivity
- current activity
- prepared candidate readiness
- Character/Speech performance上の自然なpause

ただし**生成待ち時間を会話上の沈黙時間へそのまま加算しない**。

つまり、候補が必要になる前から準備できる場合は準備し、LLM latencyを発話間隔からできるだけ隠蔽する。

---

# 11. TTSとBody同期

Presentation Laneで実際にcommitされたSpeechだけがBody speech/visemeへ渡る。

```text
Committed Speech
+ actual audio start time
+ pronunciation/viseme timeline
→ Body Realtime Layer
```

queue中の未commit候補で口を動かさない。

TTS準備中・audio playback中であってもBody full-motion controllerおよびBrain Decision Laneは継続する。

---

# 12. Queue policy

queueはboundedとする。

初期設計では原則として、

- presenting: 最大1
- immediately prepared next candidate: 少数（通常1を基準）
- unlimited future candidates: 禁止

とする。

実際の上限値は性能検証で調整可能だが、queue sizeそのものをキャラクター性や会話ロジックにしない。

backpressure時は低優先度・古い候補を破棄/再評価し、無制限LLM callを行わない。

---

# 13. Concurrency / Runtime要件

Runtime Kernelは少なくとも次を独立Task/worker境界として扱える必要がある。

- Event/Appraisal/Commander processing
- Character/Speech preparation
- TTS preparation
- Speech presentation/playback
- Body realtime frame production

一つのTaskが長時間awaitしても他レーンを停止しない。

Cancellationはcandidate_id / command_id / presentation_idで伝播できるようにする。

shutdown時は新規候補生成を停止し、queue中候補をcancelし、presentationをpolicyに従い停止/終了し、全Taskをawaitする。

---

# 14. Observability

性能・因果確認のため、本文を過剰保存せず以下の時刻をtraceする。

```text
command_decision_started_at
command_decision_completed_at
character_generation_started_at
character_generation_completed_at
semantic_validation_completed_at
speech_performance_completed_at
candidate_queued_at
preplay_revalidation_at
tts_prepare_started_at
tts_prepare_completed_at
presentation_started_at
presentation_completed_at
candidate_cancelled_at / superseded_at / stale_at
```

重要指標:

```text
next_generation_start_offset
  = next_character_generation_started_at
    - previous_presentation_started_at

presentation_gap
  = next_presentation_started_at
    - previous_presentation_completed_at
```

`next_generation_start_offset`が前Speechのdurationに比例して増える構造をFAILとする。

---

# 15. Unit Acceptance

最低限、fake clock / fake LLM / fake TTSで次を確認する。

1. Speech A playbackが5秒でも、その再生中にSpeech B Character生成が開始・完了する。
2. Speech A playbackを20秒へ延ばしてもSpeech B生成開始が20秒後へ押し出されない。
3. TTS preparationが遅くてもAppraisal/Commanderが処理を継続する。
4. Speech A再生中にユーザー入力が来るとqueued autonomous Bをcancel/supersedeできる。
5. B生成後にtopic/context revisionが変化した場合Bをstaleとして再生しない。
6. queue upper boundを越えてLLM生成を増殖させない。
7. playback failure後もDecision Laneが継続する。
8. Body/viseme同期処理がDecision Laneをblockしない。
9. cancellation時にpending taskを残さない。
10. generation traceとpresentation traceを別々に観測できる。

---

# 16. Adjacent Contract Acceptance

## Commander ↔ Speech Pipeline

- prepareとpresentation commitの意味を混同しない。
- stale候補のcommitを拒否できる。

## Character ↔ Speech Pipeline

- Characterはqueue/presentation lifecycleを意味決定に使わない。
- candidate revisionを保持する。

## Speech Performance ↔ TTS

- performance計画とaudio generationを分離する。
- provider latencyでCharacter generationをblockしない。

## Speech Pipeline ↔ Body

- commitされたspeechだけがviseme/speech realtime layerを開始する。

## Speech Pipeline ↔ Autonomy / Turn

- 自律候補の準備中/queue中/再生中をtyped factsとして参照できる。
- user turn acquisitionで候補を再評価できる。

---

# 17. Integration Verification

実LLM + 実TTSでは、発話内容の主観評価だけでなく時間軸を必ず確認する。

例:

```text
Speech A presentation started  10:00:00.000
Speech B character gen started 10:00:01.200
Speech B character gen done    10:00:04.000
Speech A presentation ended    10:00:08.000
Speech B revalidated           10:00:08.050
Speech B presentation started  10:00:08.300
```

この場合、Speech B生成はA再生中に進んでいるため構造上PASS。

以下はFAIL:

```text
Speech A presentation ended    10:00:08.000
Speech B character gen started 10:00:08.010
Speech B character gen done    10:00:12.000
Speech B presentation started  10:00:12.200
```

Aの再生完了までB生成開始を待っているため、たとえ最終的に動作してもV2要求を満たさない。

---

# 18. 非目標

- 必ず休みなく喋り続けること
- 発話間隔を0秒へ固定すること
- 未来の会話を大量に事前生成すること
- ユーザー入力を無視してqueueを消化すること
- LLM latencyを隠すための固定フィラー台詞生成
- TTS audioを無制限にキャッシュすること
- Presentation順序をCharacter LLMへ判断させること

目標は**「話すべきかどうかの自然な判断」と「生成計算上の不要な待ち」を分離すること**である。

---

# 19. V2 Design Gateへの追加条件

- [ ] #348がV2 Brain hierarchyに含まれる
- [ ] Runtime KernelがDecision/Preparation/Presentationの独立進行を支援できるContractになっている
- [ ] Autonomy / Turnがprepared/queued/presentingを区別する
- [ ] Brain Integrationにplayback中next-generation testが含まれる
- [ ] 実LLM/TTS Verificationでtime traceを確認する
- [ ] playback durationがnext generation startを構造的にblockしないことをユーザー確認前に自動テストで証明する
