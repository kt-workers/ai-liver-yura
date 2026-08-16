# AI Liver ゆら V2 Cognitive / LLM Architecture

Status: Draft / V2 Design Gate / Design Reconciliation Complete
Brain: `docs/architecture/v2/brain_architecture.md`
System: `docs/architecture/v2/system_architecture.md`
Goal / Commitment: `docs/architecture/v2/goal_commitment_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Root: #317

## 1. 目的

LLMを**どこに、何のために使うか**を定義する。

最終目標はUser Messageへの返信器ではなく、Internal State・Memory・Relationship・persistent Goal/Commitment・Attention/Focus・Activityを持ち、会話・配信・ゲーム・観察・沈黙等を自ら選ぶ「ゆら」という継続主体である。

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
→ Internal State / salience
→ Attention / Focus eligibility
→ Executive
→ Goal / Commitment transition
→ Planning / Realization / Execution
→ Actual Result
→ Appraisal / Goal / Attention / Reflection / Memory
↺
```

この図を固定直列awaitにしない。

V2 RuntimeはEvent-driven / snapshot-based / sparse activation / bounded concurrent lanes。

必須:

- 1つのLLM応答待ちでunrelated laneを止めない
- Speech playback中にnext cognition/generation可能
- Body realtimeはLLM/TTS/DB/Game AI待ちで停止しない
- Reflectionはforeground interactionをblockしない
- Game frame loopはExecutive LLM latency非依存
- Streaming burstをbounded/aggregatedに扱う
- background cognitionがforegroundをstarveしない
- stale/cancelled/superseded resultをlatest stateへ誤commitしない

---

## 3. AuthorityとLLMを分離

| Authority | Owner | LLM必須か |
|---|---|---|
| open-ended external NL meaning | #326 Input Meaning | 原則LLM候補 |
| subjective appraisal / salience candidate | #327 Appraisal | deterministic / LLM選択 |
| current Emotion/Desire/Drive等 | #327 State Reducer | **非LLM** |
| conscious Goal / Action selection | #328 Executive | LLM候補 |
| current Goal / Commitment canonical state | #366 | **非LLM** |
| current Attention / Focus / Turn scheduling | #333 | **非LLM** |
| complex Goal planning | #361 | 必要時LLM |
| Activity lifecycle / Actual Fact | #329 | **非LLM** |
| What to say | #362 | simple非LLM可 / complex LLM |
| How to say it | #330 | LLM候補 |
| speech semantic observation | #363 | policyでLLM候補 |
| Body high-level motion composition | #338 | 必要時LLM |
| Body physical/realtime continuity | #339/#340 | **非LLM** |
| Memory Candidate generation | #364 | background LLM候補 |
| Memory canonical store/retrieval | #332 | **非LLM** |
| Game frame-level skill | #365 | Skill AI方式選択 |

LLMに「考えさせること」と、正本State/Factを「所有させること」を分ける。

---

## 4. Request / Revision Contract

long-running requestは責務上必要なrevisionを持つ。

```text
request_id
role_id
source_event_ids[]
source_context_revision
goal_revision?
attention_revision?
internal_state_revision?  # Internal Stateを読むExecutive等の責務固有stamp
priority
preconditions[]
interruptibility
stale_policy
```

```text
LLM result
→ schema validation
→ responsibility validation
→ await後にcurrent stateを再取得
→ authority / revision / capability / precondition checks
→ typed candidate / plan / observation
→ owning Module commits
```

LLM自由文をInternal State / Goal State / Focus State / Execution Factへ直接代入しない。

---

## 5. Core Cognitive LLM Role候補

Role総数はArchitecture invariantではない。

### C01 Input Meaning — #326

**外部から何が伝えられたのか。**

natural language → `StructuredInputMeaning`。
主観評価・Goal選択はしない。bounded ReferenceContextを使い、finite keyword/regexをopen-ended semantic fallbackにしない。

### C02 Subjective Appraisal — #327

**この出来事は現在のゆらにとってどういう意味を持つか。**

Internal State、Relationship、Goal/Commitment、Activity、Values等で評価する。
LLM利用時も`AppraisalCandidate / StateDeltaProposal / salience candidate`を返すだけでState/Focus/Goalを直接mutationしない。
Deep Appraisalを全Decisionのblocking prerequisiteにしない。

### C03 Executive Deliberation — #328

**私は今、何をしたい／する／しないか。**

唯一のconscious Goal/Action Authority。
`ExecutiveDecision`としてGoal/Commitment transition intent、Speech/Body/Activity/attention intent等を出せるが各State Storeを直接書き換えない。

### C04 Goal / Activity Planning — #361

**active Goalをどう実行するか。**

#366の`goal_id / goal_revision`を受けcomplex GoalをActivityPlanへ分解する。Goal自体を変更しない。

typed snapshot・candidate・commit gate・simple/complex経路の実装正本は[`goal_planning_contracts.md`](goal_planning_contracts.md)とする。

### C05 Speech Semantics — #362

**Speech Intentを実現するため何を伝えるか。**

What-to-say Authority。propositions、required/forbidden、polarity/certainty/degree、question budget、truth constraints等を`SpeechSemanticPlan`へ閉じる。simple pathでは専用LLM省略可能。

実装正本は`speech_semantics_contracts.md`。simple pathはtyped directiveの存在で決定し、keyword / regex / fixed phraseをfallback Authorityにしない。complex pathはFoundation LLM Roleのcandidateをawait後live revisionで再検証し、同じDomain commit gateへ通す。

### C06 Character Language — #330

**確定意味を、ゆらならどう言うか。**

How-to-say。Goal / Fact / What-to-say Authorityを奪わない。

### C07 Independent Semantic Verification — #363

**CharacterUtteranceはSpeechSemanticPlanを意味的に保持するか。**

Observerのみ。Speech Intent変更、Character直接指揮、Runtime Fact変更、free-form final Authorityなし。final accept/rejectはtyped observation + closed policy。

required verifier待ち中もsafe Performance/TTS prepをparallel可能。PASS前にexternal Presentation commitしない。

### C08 Body Motion Planning — #338

**BodyIntentをcurrent bodyからどう運動へ実現するか。**

LLMは必要時。毎frame joint angleやrenderer-specific parameterを生成しない。physical continuityはdeterministic Bodyが所有。

### C09 Reflection — #364

**今回の経験から何を長期的に覚える価値があるか。**

Conversation / Stream / Game / Activity Result等からMemoryCandidateを生成し#332へ渡す。foreground interactionをblockしない。

---

## 6. Persistent Goal / Commitment — #366

Executiveの意思がnext turn/context truncationで消えないよう、typed persistent stateを持つ。

```text
Executive decision
→ validated Goal transition
→ Goal State #366
→ later Attention / Executive / Planner
```

Goal StateはLLM Roleではない。

- Executive = Goal採用/放棄Authority
- #366 = lifecycle/revision/current state owner
- #361 = execution method only
- #329 = Activity/Actual Fact only
- #332/#364 = past/evidence only

---

## 7. Attention / Focus / Turn — #333

Game、Streaming、Conversation、Reflection等の全EventをExecutiveへ無制限同期投入しない。

```text
Appraisal salience candidate
+ Executive attention intent
+ user/turn priority
+ Goal/Activity context
→ AttentionFocusState / bounded scheduling
→ eligible Executive triggers
```

#333 owns:

- foreground focus
- secondary monitors
- turn / response obligation
- attention/source budgets
- interrupt thresholds
- fairness / anti-starvation

#333 does not own:

- NL meaning
- Goal/Action decision
- Speech content
- Internal State

Body gazeはFocusの身体表現でありcognitive Attention Authorityではない。

---

## 8. LLMを使わない方がよい責務

- Event queue / scheduler / clock
- cancellation / priority / backpressure
- schema / permission / authority checks
- Internal State reducer
- Goal / Commitment reducer
- Attention / Turn state reducer/scheduler
- Activity lifecycle / Actual Fact
- Body IK/FK/limits/balance/interpolation
- Speech queue / playback lifecycle
- Persistence transaction
- secret handling

LLMが「成功した」と答えてもActual Factにしない。

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

frame-level操作をExecutive LLMへ毎frame問い合わせない。

### Streaming #347

spam/duplicate grouping、clustering、moderation candidate、rolling summary等にAI利用可。
誰へ返すか、何を言うか、配信継続はCore Authority。

### Perception

Vision/audio modelはtyped perceptをInput Gatewayへ返し、Internal State/Goalを直接変更しない。

---

## 10. Role分離基準

新LLM Roleは最低限:

1. 独立質問を1文で表現可能
2. typed input/output
3. Authority重複なし
4. Unit/model evaluation可能
5. 独立交換/停止可能
6. failure/degradation定義可能
7. deterministicでは不足する理由がある

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

- LLM総数を固定しない
- ExecutiveへAuthorityを一本化
- Goal/CommitmentをPromptだけに保持しない
- multi-activity Attentionを明示
- Executiveへhigh-frequency Eventを無制限同期投入しない
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
8. `decide → act → observe → appraise → state/goal/memory → decide` closed loop.
9. このloopをglobal blocking Pipelineにしない。

---

## 13. Design Reconciliation Status

設計反映は完了済み。

- [x] 4 LLM固定撤回
- [x] Single Executive Authority
- [x] Goal Planning #361
- [x] Speech Semantics #362
- [x] Character #330 = How-to-say
- [x] Semantic Verification #363 = Observer
- [x] Appraisal #327 = deterministic / LLM selectable
- [x] Reflection #364 / Memory Store #332分離
- [x] Runtime #322 = concurrent orchestration
- [x] Speech #348 non-blocking
- [x] Game Skill #365 / Streaming Skill AI分離
- [x] Persistent Goal State #366
- [x] Attention / Focus #333
- [x] Project sync manifest/runbookへ#333/#366反映
- [x] Legacy Migration MatrixへGoal/Attention failure classを追補
- [x] subordinate canonical / Issue cross-audit

残るDesign Gateは**ユーザーによるV2 canonical architecture確認**。

#319 actual Projects v2 mutationは実行環境制約で別途Blocked管理する。
Product implementationはユーザー確認前に開始しない。
