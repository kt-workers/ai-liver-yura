# AI Liver ゆら V2 Cognitive / LLM Architecture

Status: Draft / V2 Design Gate
Brain: `docs/architecture/v2/brain_architecture.md`
System: `docs/architecture/v2/system_architecture.md`
Goal / Commitment: `docs/architecture/v2/goal_commitment_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Root: #317

## 1. 目的

LLMを**どこに、何のために使うか**を定義する。

最終目標はUser Messageへ返答するchatbotではなく、Internal State・Memory・Relationship・persistent Goal/Commitment・Activity・Attention/Focusを持ち、会話・配信・ゲーム・観察・沈黙等を自ら選ぶ「ゆら」という継続主体である。

LLM個数を先に固定しない。

> open-endedな意味理解・主観評価・推論・計画・言語実現・意味検証・身体運動構成・内省に独立責務があり、LLMが適切な場合だけ専用Roleを設ける。

ただし:

> **conscious Goal / Action selectionの最終AuthorityはExecutive #328ただ1つ。**

---

## 2. 認知サイクルはblocking Pipelineではない

因果モデル:

```text
Events
→ Meaning / Perception
→ Appraisal
→ Internal State / Attention relevance
→ Executive
→ Goal / Commitment transition
→ Planning / Realization / Execution
→ Actual Result
→ Appraisal / Goal / Attention / Reflection / Memory
↺
```

禁止:

```text
Meaning LLM
→ await Appraisal LLM
→ await Executive LLM
→ await Planner LLM
→ await Speech Semantics LLM
→ await Character LLM
→ await Verifier LLM
→ await TTS/playback
→ next cycle
```

V2はEvent-driven / snapshot-based / sparse activation / bounded concurrent lanes。

---

## 3. AuthorityとLLMを分離

| Authority | Owner | LLM必須か |
|---|---|---|
| open-ended外部NLの意味 | Input Meaning #326 | 原則LLM候補 |
| subjective appraisal / salience candidate | Appraisal #327 | deterministic / LLM選択 |
| current Emotion/Desire/Drive等 | State Reducer #327 | **非LLM** |
| conscious Goal / Action選択 | Executive #328 | LLM候補 |
| current Goal / Commitment正本 | Goal State #366 | **非LLM** |
| current Focus / Turn / attention scheduling | Attention #333 | **非LLM** |
| 複雑Goalの実行計画 | Planner #361 | 必要時LLM |
| Activity lifecycle / Actual Fact | #329 | **非LLM** |
| What to say | Speech Semantics #362 | simple非LLM可 / complex LLM |
| How to say it | Character #330 | LLM候補 |
| 発話意味保持の観測 | Verifier #363 | risk policyでLLM候補 |
| Body high-level motion composition | #338 | 必要時LLM |
| Body physical/realtime continuity | #339/#340 | **非LLM** |
| Memory Candidate生成 | Reflection #364 | background LLM候補 |
| Memory正本 / Retrieval | #332 | **非LLM** |
| Game frame-level技能 | #365 | Skill AI方式選択 |

LLMに「考えさせること」と正本State/Factを「所有させること」を分ける。

---

## 4. Snapshot / Candidate Model

long-running requestは必要なrevisionを保持する。

```text
request_id
role_id
source_event_ids[]
source_context_revision
goal_revision?
attention_revision?
priority
preconditions[]
interruptibility
stale_policy
```

```text
LLM result
→ schema validation
→ responsibility validation
→ authority / revision / precondition checks
→ typed candidate / plan / observation
→ owning Module commits
```

LLM自由文をDomain State / Goal State / Focus State / Execution Factへ直接代入しない。

---

## 5. Core Cognitive LLM Role候補

Role数は固定しない。

### C01 Input Meaning — #326

質問: **外部から何が伝えられたのか。**

自然言語→`StructuredInputMeaning`。

- 主観評価しない
- Goal/Actionを選ばない
- structured inputを無理に文章化しない
- bounded ReferenceContext
- finite keyword/regexをsemantic fallbackにしない

### C02 Subjective Appraisal — #327

質問: **この出来事は現在のゆらにとってどういう意味を持つか。**

Internal State、Relationship、Goal/Commitment、Activity、Values等を踏まえて評価。

LLM利用時も`AppraisalCandidate / StateDeltaProposal / salience candidate`を返すだけ。
State / Focus / Goalを直接mutationしない。

Deep Appraisalを全Decisionのblocking prerequisiteにしない。

### C03 Executive Deliberation — #328

質問: **私は今、何をしたい／する／しないか。**

唯一のconscious Goal/Action Authority。

入力には必要な範囲で:

- Meaning / Appraisal / Internal State
- Memory / Relationship
- GoalContextView
- AttentionFocusView
- Activity / Capability / Execution facts
- Speech / Body state
- environment/time

出力`ExecutiveDecision`にはGoal/Commitment transition intent、Speech/Body/Activity/attention intent等を含める。

### C04 Goal / Activity Planning — #361

質問: **active Goalをどう実行するか。**

`goal_id / goal_revision`を受け、complex GoalだけをActivityPlanへ分解。Goal自体を変更しない。

### C05 Speech Semantics — #362

質問: **Speech Intentを実現するため何を伝えるか。**

`What to say != How to say it`。

propositions、required/forbidden、certainty/polarity/degree、question budget、truth constraints等を`SpeechSemanticPlan`へ閉じる。

simple pathは専用LLM省略可能。

### C06 Character Language — #330

質問: **確定意味を、ゆらならどう言うか。**

Character styleを表現するがGoal / Fact / What-to-say Authorityを奪わない。

### C07 Independent Semantic Verification — #363

質問: **CharacterUtteranceはSpeechSemanticPlanを意味的に保持するか。**

Observerのみ。

- Speech Intent変更なし
- Character直接指揮なし
- Runtime Fact変更なし
- free-form final Authorityなし

final accept/rejectはtyped observation + closed policy。

required verifier待ち中もsafe Performance/TTS prepをparallel可能。PASS前にexternal Presentation commitしない。

### C08 Body Motion Planning — #338

質問: **BodyIntentをcurrent bodyからどう運動へ実現するか。**

LLMは必要時。毎frame joint angleやrenderer-specific parameterを生成しない。physical continuityはdeterministic Bodyが所有。

### C09 Reflection — #364

質問: **今回の経験から何を長期的に覚える価値があるか。**

Conversation / Stream / Game / Activity Result等からMemoryCandidateを生成し#332へ渡す。

foreground interactionをblockしない。

---

## 6. Persistent Goal / CommitmentはLLMではない — #366

Executiveが「やりたい」と決めても次turn/context truncationで消えては主体の継続性がない。

```text
Executive decision
→ validated Goal transition
→ Goal State #366
→ later Snapshot / Attention / Planner
```

Goal Stateがtyped lifecycle / revisionを所有し、ExecutiveがGoal採用/放棄Authorityを持つ。

Planner / Activity / Memoryと分離する。

---

## 7. Attention / FocusはLLMではない — #333

配信・Game・Conversationが同時にあるとき、すべてのEventをExecutiveへ無制限同期投入しない。

```text
Appraisal salience candidates
+ Executive attention intent
+ user priority / turn facts
+ Activity / Goal context
→ AttentionFocusState / bounded scheduling
→ eligible Executive triggers
```

Attention #333が所有する:

- foreground focus
- secondary monitors
- turn ownership
- response obligation
- attention/source budgets
- interrupt thresholds
- fairness / anti-starvation

Attention #333が所有しない:

- NL意味
- Goal/Action decision
- Speech内容
- Internal State

Game frame/comment burstはSubsystem側でもaggregateし、Attention budgetでboundedに扱う。

Body gazeはFocusの表現であってcognitive Attention Authorityではない。

---

## 8. LLMを使わない方がよい責務

- Event queue / scheduler / clock
- cancellation / priority / backpressure
- schema / permission / authority checks
- Internal State reducer
- Goal / Commitment reducer
- Attention / Turn state reducer/scheduler
- Activity lifecycle / Execution Fact
- Body limits / IK/FK/balance/interpolation
- Speech queue / playback lifecycle
- Persistence transaction
- secret handling

LLMが「成功した」と答えてもActual Factにはしない。

---

## 9. Skill AIとCore Cognitive AIを分離

### Game #365

```text
Executive Goal / Strategy
→ Game Skill Runtime
→ realtime game-specific agent
→ controller
→ salient Game Event / Result
→ Appraisal / Attention / Executive
```

Game AgentはLLM/VLM/RL/search/deterministic/hybridを選べるがCore Goal Authorityなし。frame-level操作をExecutive LLMへ毎frame問い合わせない。

### Streaming #347

spam/duplicate grouping、clustering、moderation candidate、rolling summary等にAI利用可。

誰へ返すか、何を言うか、配信継続はCore Authority。

### Perception

Vision/audio modelはtyped perceptをInput Gatewayへ返すだけでInternal State/Goalを直接変更しない。

---

## 10. Role分離基準

新LLM Roleは最低限:

1. 独立した質問を1文で表現できる
2. typed input/output
3. Authority重複なし
4. Unit/model evaluation可能
5. 独立交換/停止可能
6. failure/degradation定義可能
7. deterministicでは不足する理由がある

「賢くしたい」だけでRoleを増やさない。

Role分離しても別API callを毎回直列に行う必要はない。

---

## 11. V1から継承する教訓

維持:

- 責務分離そのもの
- Input Meaning vs Decision
- What-to-say vs How-to-say
- Characterへraw stateを解釈させない
- independent semantic verification
- finite lexical matcher非Authority
- structured typed output
- failure classベース改善

改善:

- LLM総数を先に固定しない
- ExecutiveへAuthorityを一本化
- Goal/CommitmentをPromptだけに保持しない
- multi-activity Attentionを明示
- Executiveへ全high-frequency Eventを同期投入しない
- long LLM/TTS/playback/Memory/Game処理を直列awaitしない

---

## 12. 自由意志に近づける必須要素

1. User input = Event, not unconditional command.
2. Persistent Internal State.
3. Persistent Goal / Commitment #366.
4. Bounded Attention / Focus #333.
5. Internal autonomous triggers.
6. Single Executive Authority.
7. Actual result feedback.
8. `decide → act → observe → appraise → state/goal/memory → decide`のclosed loop。
9. このloopをglobal blocking Pipelineにしない。

---

## 13. Design Reconciliation Status

- [x] 4 LLM固定撤回
- [x] Single Executive Authority
- [x] Goal Planning #361分離
- [x] Speech Semantics #362分離
- [x] Character #330をHow-to-sayへ限定
- [x] Semantic Verification #363をObserver化
- [x] Appraisal #327をLLM/deterministic選択可能化
- [x] Reflection #364をMemory Store #332から分離
- [x] Runtime #322をconcurrent orchestration化
- [x] Speech #348 non-blocking invariant一般化
- [x] Game Skill #365 / Streaming Skill AI分離
- [x] Persistent Goal State #366追加
- [x] Attention / Focus #333を非LLM scheduling責務として明示
- [x] Project sync manifest/runbookへ#366反映
- [x] Legacy Migration MatrixをCognitive再設計へ再マッピング（#366追加追補はDesign Auditで実施）

残るDesign Gate:

- [ ] Legacy Migration Matrixへ#366 / Attention責務を最終追補
- [ ] subordinate canonical / Issue全体の最終整合監査
- [ ] #317 Design Reconciliation Checkpoint
- [ ] ユーザーによるV2 canonical architecture確認

製品コード実装は#317 Design Gate解除まで開始しない。
