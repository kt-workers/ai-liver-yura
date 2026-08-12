# AI Liver ゆら V2 Cognitive / LLM Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/brain_architecture.md`
System architecture: `docs/architecture/v2/system_architecture.md`
Root management: #317

## 1. 目的

この文書は、AI Liver ゆらでLLMをどこに、何のために使うかを定義する。

V2の最終目標は、ユーザー入力へ応答するチャットボットではない。

ゆらは、持続する内部状態・記憶・関係・欲求・目標・活動を持ち、外界と自分自身の変化を受け取りながら、会話、YouTube等でのライブ配信、ゲーム、観察、沈黙その他の活動を自ら選択できる主体として設計する。

LLMの個数を先に固定しない。

> open-endedな意味理解・主観評価・推論・計画・言語実現・意味検証・身体運動構成・内省に独立した責務が存在し、LLMが適切な場合に専用Roleを設ける。

ただし、LLM Roleを増やすことと意思決定Authorityを増やすことは別である。

> ゆらの意識的な行動・目標選択の最終AuthorityはExecutive Deliberatorただ1つとする。

---

## 2. 「認知サイクル」は1本の直列Pipelineではない

本書でいう認知サイクルは、出来事・評価・状態・意思決定・実行結果が循環して影響し合う**因果関係**を意味する。

実装を次のような1本のblocking chainにはしない。

```text
Input
→ Meaning
→ Appraisal
→ Executive
→ Speech
→ TTS
→ Playback完了
→ Body完了
→ Memory保存完了
→ next cycle
```

この構造は禁止する。長いLLM推論、TTS、音声再生、Body motion、Game、Streaming、Memory処理のいずれかが、他の認知・入力処理を滞留させるためである。

V2では、**Event-driven / snapshot-based / concurrent lanes** を正規構造とする。

```text
                         ┌─ Perception / Input lane
                         │
External / Internal ────→ Event Bus / Typed Event Stream
                         │
                         ├─ Appraisal / State lane
                         │
                         ├─ Executive Deliberation lane
                         │
                         ├─ Speech Preparation lane
                         │    ├─ Speech Semantics
                         │    ├─ Character Realizer
                         │    └─ Semantic Verification
                         │
                         ├─ Speech Presentation lane
                         │    ├─ TTS preparation
                         │    └─ playback
                         │
                         ├─ Body realtime lane
                         │
                         ├─ Activity / Game / Streaming lanes
                         │
                         └─ Reflection / Memory Consolidation lane

Each lane
  → typed result / fact / state transition event
  → Event Bus
  → interested lanes may react
```

### 2.1 必須Concurrency invariant

- Speech Aの再生中でも、次のInput Meaning / Appraisal / Executive / Speech preparationを進められる。
- TTS待機中でもExecutiveは別Eventを処理できる。
- Body realtime更新はLLM、TTS、DB、Game AIを待たない。
- Memory consolidationは通常の会話・Body・Activityをblockしない。
- Gameのframe-level処理をCore Executive LLMの応答待ちにしない。
- Streamingのコメント大量処理でCore decision loopを止めない。
- 1つのProvider障害・timeoutが他Roleのtask schedulingを停止させない。
- shutdown/cancelは各laneを独立して収束させ、pending taskを残さない。

### 2.2 同時実行と因果整合性

並行化しても古い文脈の結果を無条件採用しない。

各long-running処理は最低限、次を持つ。

```text
request_id
source_event_ids
source_context_revision
created_at
priority
interruptibility
expires_at / stale policy
preconditions
```

結果をcommitする前に、必要に応じて現在のrevision / preconditionを再検証する。

例:

```text
Speech candidate B generated while Speech A is playing
↓
new user input arrives
↓
B's source_context_revision becomes stale
↓
revalidate / cancel / supersede
↓
古いBを自動再生しない
```

### 2.3 Snapshotの原則

各RoleがCoreのmutable objectを長時間直接共有しない。

開始時点のtyped snapshot / read modelを受け取り、結果をcandidate / eventとして返す。

現在状態の書込みAuthorityはそれぞれの所有Moduleだけが持つ。

---

## 3. 継続的な認知・行動の因果モデル

```text
External / Internal sources
  ├─ user conversation
  ├─ YouTube viewers / stream events
  ├─ game state / result
  ├─ camera / microphone / touch
  ├─ time / schedule / environment
  ├─ memory activation
  ├─ internal state changes
  └─ previous execution results
            ↓ typed events
Perception / Meaning
            ↓
Subjective Appraisal
            ↓
Internal State / Motivation / Goal relevance
            ↓
Executive Deliberation
            ↓
Intent / Goal / Commitment
            ↓
Planning / Realization
   ├─ Activity planning
   ├─ Speech semantics
   ├─ Character language
   └─ Body motion
            ↓
Execution
   ├─ conversation
   ├─ streaming
   ├─ game
   ├─ plugin capability
   ├─ body / attention
   └─ silence / observation
            ↓
Execution Result / World change
            ↓
Appraisal / Memory / Reflection
```

この図は因果関係であり、すべての箱を毎回順番にawaitする実行Pipelineではない。

ユーザー入力は重要なEventだが常に最上位命令ではない。ゆらは現在の関係、状態、目標、約束、Activity、Capability、Values等を踏まえ、応答、拒否、延期、質問、沈黙、別Activity継続等を選べる。

---

## 4. AuthorityとLLM Roleを分離する

最低Authorityは次のように一意にする。

| Authority | Owner |
|---|---|
| 外部自然言語が何を意味するか | Input Meaning |
| 出来事がゆらにとってどう評価されるか | Appraisal contract |
| 現在のEmotion / Desire / Drive等の状態 | Internal State Reducer |
| 今何をしたい／する／しないか | Executive Deliberator |
| 複雑なGoalをどう実行するか | Activity Planner（Executiveに従属） |
| 発言として何を伝えるか | Speech Semantics Planner（Executive Intentに従属） |
| それをゆららしくどう言うか | Character Language Realizer |
| Character発話が意味を保持したかの観測 | Independent Semantic Verifier |
| 身体意図をどう運動として実現するか | Body Motion Planner |
| 実際に何が起きたか | Execution Result / Runtime facts |
| Memoryの永続正本 | Memory Store + validation pipeline |

各LLMの出力はtyped candidate / plan / observationとして扱う。

```text
LLM output
→ schema validation
→ responsibility-specific validation
→ authority / precondition / fact checks
→ accepted typed result
```

LLMの自由文をDomain StateやExecution Factへ直接代入しない。

---

## 5. Core Cognitive LLM Roles

ここに挙げるRoleは初期設計候補であり、個数をArchitecture invariantとして固定しない。

Role追加・統合・非LLM化は、責務・Authority・入力出力Contract・失敗時挙動を説明できる場合のみ行う。

### C01 Input Meaning / Perception Interpretation

質問: **外部から何が伝えられたのか。**

- user text / STT transcript / stream chat等の自然言語をtyped semanticsへ変換する。
- bounded reference contextを利用できる。
- 「ゆらがどう感じるか」「従うか」「何をするか」は決めない。
- Game stateやTouch等、既に構造化できる入力は無理に自然言語LLMへ通さない。

### C02 Subjective Appraisal

質問: **この出来事は、現在のゆらにとってどういう意味を持つか。**

Input Meaningとは別責務。同じ出来事でもEnergy、Desire、Relationship、Current Goal、Values、Recent Experience等により主観的意味は変わる。

LLMを利用する場合も出力は`AppraisalCandidate` / `StateDeltaProposal`であり、Internal Stateを直接書き換えない。

```text
Appraisal LLM / evaluator
→ typed AppraisalCandidate
→ StateTransitionValidator
→ StateReducer
→ current state
```

単純で明確なAppraisalはdeterministic rule/modelで処理してよい。LLM利用を必須化しない。

### C03 Executive Deliberation

質問: **私は今、何をしたい／何をする／何をしないか。**

ゆらの意識的行動選択の唯一の最終Authority。

入力候補:

- current event / meaning
- Appraisal
- Emotion / Desire / Drive / Motivation
- Values / Moral context
- Memory evidence
- Relationship
- current goals / commitments
- current activities
- capabilities
- execution facts
- turn / interruption state
- time / environment

出力は`ExecutiveDecision` / high-level `SystemCommand`。

Character、Body、Activity Planner、Game Agent等はExecutive Authorityを奪わない。

### C04 Activity / Goal Planning

質問: **Executiveが選んだ目的を、どう実行するか。**

「YouTubeでゲーム配信したい」等の複雑Goalを複数step、Capability、失敗回復を含むtyped `ActivityPlan`へする。

単純ActionではPlanner LLMを呼ばず決定論的Executorへ直接渡してよい。PlannerはGoal自体を勝手に変更しない。

### C05 Speech Semantics Planning

質問: **このSpeech Intentを実現するために、何を伝えるか。**

V1で得た`What to say != How to say it`の責務分離を維持する。

```text
Executive SpeechIntent
+ Appraisal / facts / memory evidence / discourse constraints
→ Speech Semantics Planner
→ SpeechSemanticPlan
```

出力候補:

- propositions
- required / optional / forbidden content
- certainty / polarity / degree等のsemantic facet
- self-disclosure level
- question / new-direction budget
- execution truth constraints

Character Profileは事実決定Authorityにしない。

### C06 Character Language Realization

質問: **確定済みの意味を、ゆらならどう言うか。**

```text
SpeechSemanticPlan
+ Character Language Projection
+ interpersonal / discourse / expression context
→ Character Language Realizer
→ CharacterUtterance
```

Goal、Emotion、Execution Fact等を再解釈して発言意味を変更しない。

### C07 Independent Semantic Verification

質問: **CharacterUtteranceはSpeechSemanticPlanの意味を実際に保持しているか。**

独立Verifierを「LLMが増えるから」という理由だけで排除しない。

```text
SpeechSemanticPlan
+ CharacterUtterance
→ Independent Semantic Verifier
→ typed SemanticRelationObservation
→ deterministic acceptance policy
```

VerifierはObserverであり、Speech Intentを決めず、Characterを直接指揮せず、Runtime Factを書き換えず、final accept/reject policyを自由文で所有しない。

Verifier不要で同等以上の保証ができる将来方式が成立した場合はContract Gateを通して非LLM化してよい。

### C08 Body Motion Planning

質問: **高レベルBody Intentを、現在の身体からどう動いて実現するか。**

```text
BodyIntent
+ current Body State
+ Canonical Skeleton / DOF / limits
+ Body Expression Context
+ Character Body Style
→ Body Motion Planner LLM
→ BodyMotionPlan
→ deterministic compiler / IK / FK / limits / balance
→ Continuous Controller
→ BodyPoseFrame
```

LLMは毎frame joint angle、Live2D parameter、renderer固有bone名を生成しない。

### C09 Reflection / Memory Consolidation

質問: **今回の経験から、何を長期的に覚える価値があるか。**

会話、配信、ゲーム、活動結果からepisodic / semantic / relationship / preference / skill candidatesを生成できる。

```text
Typed events / results / state transitions
→ Reflection / Consolidation
→ MemoryCandidates
→ provenance / contradiction / freshness / importance validation
→ Memory Store
```

Reflection LLMはMemory DBへ直接自由文を書き込むAuthorityを持たない。Activity終了、idle、一定量蓄積時等に非同期実行できる。

---

## 6. LLMを使わない方がよい責務

原則として以下はdeterministic / typed runtimeを優先する。

- Event queue / scheduler / cancellation / clock
- Capability availability
- Authority / permission checks
- schema validation
- execution lifecycle facts
- Internal Stateの最終Reducer
- resource ownership
- retry / backoff / timeout policy
- Body joint limits / collision / IK / FK / balance / interpolation
- TTS playback timing
- speech queue lifecycle
- persistence transaction
- secret handling

LLMが「成功したと思う」と答えてもExecution Factにはしない。

---

## 7. Core Cognitive AIとSkill / Subsystem AIを分離する

ゲーム、配信、Vision等では、その能力に適した別AIを利用してよい。

### 7.1 Game

```text
Yura Executive
→ Goal / Strategy / Activity Intent
→ Game capability / subsystem
→ game-specific agent
   - LLM / VLM
   - RL model
   - search/planning algorithm
   - deterministic policy
→ controller/action
→ Game Result
→ Core Appraisal
```

Game Agentは高速な戦術技能を担当できるが、ゆら自身のGoalを勝手に変更しない。対戦中のframe-level action selectionをCore Executive LLMへ毎frame問い合わせない。

### 7.2 Streaming

大量コメント分類、moderation補助、chat summarization、配信情報整理等に専用モデルを使ってよい。

それらはCore Executiveの代わりに「配信するか」「誰へどう返すか」を最終決定しない。

### 7.3 Perception

Vision / audio recognition等も専用VLM / speech modelを利用してよい。認識結果はtyped perceptとしてCoreへ渡し、認識モデルがCore内部状態を直接変更しない。

---

## 8. Role分離の基準

新しいLLM Roleを追加する場合、最低限次を満たす。

1. 独立した質問を1文で表現できる。
2. 入力と出力をtyped contractとして定義できる。
3. 既存RoleとAuthorityが重複しない。
4. 単独Unit / model evaluationが可能である。
5. そのRoleだけを交換・改善・停止できる。
6. failure時のfallback / degradationが定義できる。
7. LLMが本当に適切であり、deterministic処理で十分な責務を無理にLLM化していない。

逆に、1つのRoleが複数の独立した質問を持ち、別々に検証・交換したい場合は責務過剰を疑う。

---

## 9. V1から継承する教訓

V1で責務分離したこと自体は失敗ではない。

維持する教訓:

- Input MeaningとInternal Directive / Decisionを分離する。
- `What to say`と`How to say it`を分離する。
- Characterへraw内部状態を解釈させて事実決定させない。
- Character発話の意味保持を独立検証可能にする。
- finite word / regex / substringをopen-ended semantic authorityにしない。
- LLM outputをtyped contractへ閉じる。
- Module単位でUnit → Adjacent Contract → Integrationを行う。
- 実LLMの失敗を個別文言パッチではなくfailure classとして設計へ戻す。

改善する教訓:

- LLMの総数を先に制限しない。
- ただしAuthorityを分散させない。
- Commander / Executiveへ意味決定、活動計画、発話内容、表現を過剰集中させない。
- Verifierを自由文の最終Authorityにしない。
- 長いLLM/TTS/Playback/Memory/Game処理を直列awaitしない。

---

## 10. 自由意志に近づけるための必須要素

### 10.1 User input is an event, not an unconditional command

ユーザー入力は重要な社会的Eventとして評価するが、常に実行命令として扱わない。

### 10.2 Persistent goals and commitments

ゆらはturnを跨いだGoal、約束、Activity、未完了Intentを持てる。

### 10.3 Internal autonomous triggers

ユーザー入力がなくても、Desire、Interest、Memory activation、時間、Activity Result、環境変化からExecutive Deliberationを起動できる。

### 10.4 Single Executive Authority

意識的Goal / Action selectionの最終AuthorityをExecutive Deliberatorへ一本化する。

### 10.5 Closed experience loop

```text
decide
→ act
→ observe actual result
→ appraise
→ state changes
→ remember / reflect
→ decide again
```

ただしこのloopは因果モデルであり、各処理を1本のblocking pipelineとして直列実行しない。

---

## 11. Design Gate

この設計をV2へ反映する際は、少なくとも以下を再設計する。

- `system_architecture.md` の「4 LLM固定」を撤回する。
- `brain_architecture.md` のLLM Role invariantを本書へ置換する。
- CommanderをExecutive Deliberationへ再定義し、Activity Planning / Speech Semanticsを分離する。
- Appraisalを「非LLM固定」から「typed Appraisal responsibility。実装はLLM/deterministicを評価して選択」へ変更する。
- Character Semantic Verificationを独立Roleとして再評価する。
- Memory Consolidation / Reflectionを独立責務として設計する。
- Runtime Kernelは複数laneのevent/task orchestrationを支えるが、Domain判断を持たない。
- Speech Pipelineのnon-blocking invariantをCore全体のconcurrency invariantへ一般化する。
- Game / Streaming等のSkill AIをCore cognitive LLM Role数から分離する。

製品コード実装は、更新後のV2 canonical architectureをユーザーが確認するまで開始しない。
