# AI Liver ゆら V2 Cognitive / LLM Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/brain_architecture.md`
System architecture: `docs/architecture/v2/system_architecture.md`
Goal / Commitment: `docs/architecture/v2/goal_commitment_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Root management: #317

## 1. 目的

この文書は、AI Liver ゆらでLLMを**どこに、何のために使うか**を定義する。

最終目標はユーザー入力へ返答するチャットボットではなく、持続する内部状態・記憶・関係・Goal・Commitment・Activityを持ち、会話・配信・ゲーム・観察・沈黙等を自ら選択する「ゆら」という主体である。

LLM個数を先に固定しない。

> open-endedな意味理解・主観評価・推論・計画・言語実現・意味検証・身体運動構成・内省に独立責務があり、LLMが適切な場合だけ専用Roleを設ける。

ただしRole数とAuthority数は別。

> **ゆらのconscious Goal / Action selectionの最終AuthorityはExecutive Deliberator #328ただ1つ。**

---

## 2. 認知サイクルは1本のblocking Pipelineではない

因果モデル:

```text
External / Internal Events
→ Meaning / Perception
→ Appraisal
→ Internal State
→ Executive Deliberation
→ Goal / Commitment transition
→ Planning / Realization / Execution
→ Actual Result
→ Appraisal / Reflection / Memory
↺
```

これは固定Runtime順序ではない。

禁止:

```text
Input Meaning LLM
→ await Appraisal LLM
→ await Executive LLM
→ await Planner LLM
→ await Speech Semantics LLM
→ await Character LLM
→ await Verifier LLM
→ await TTS
→ await playback
→ await Memory
→ next cycle
```

V2はEvent-driven / snapshot-based / sparse activation / concurrent lanesを正規構造とする。

### 必須Concurrency invariant

- 1つのLLM応答待ちでunrelated laneを止めない
- Speech playback中にnext cognition / generation可能
- TTS待機中もnew input受付可能
- Body realtimeはLLM / TTS / DB / Game AI待ちで停止しない
- Reflectionはforeground interactionをblockしない
- Game frame loopはExecutive LLM latency非依存
- Streaming burstでCore starvationなし
- background cognitionがforeground interactionをstarveしない
- stale/cancelled/superseded resultを最新stateへ誤commitしない

---

## 3. Snapshot / Candidate model

long-running Roleは開始時点のtyped snapshot/read modelを受ける。

```text
request_id
role_id
source_event_ids[]
source_context_revision
goal_revision?
priority
interruptibility
preconditions[]
stale_policy
```

結果はDomain Stateへ直接書き込まず:

```text
LLM output
→ schema validation
→ responsibility validation
→ authority / revision / precondition checks
→ typed candidate / plan / observation
→ owning Module commits if valid
```

各Roleがmutable Core objectを長時間直接共有しない。

---

## 4. AuthorityとLLMを分離する

| Authority | Owner | LLM必須か |
|---|---|---|
| open-ended外部自然言語の意味 | Input Meaning #326 | 原則LLM候補 |
| 出来事の主観的評価 | Appraisal #327 | deterministic / LLM選択 |
| current Emotion/Desire/Drive等 | Internal State Reducer #327 | **LLMではない** |
| conscious Goal / Action選択 | Executive #328 | LLM候補 |
| current Goal / Commitment正本 | Goal State #366 | **LLMではない** |
| 複雑Goalの実行計画 | Goal Planner #361 | 必要時LLM |
| Activity lifecycle | Activity Runtime #329 | **LLMではない** |
| Actual Execution Fact | Execution Coordination #329 | **LLMではない** |
| What to say | Speech Semantics #362 | simpleは非LLM可 / complexでLLM |
| How to say it | Character Language #330 | LLM候補 |
| 発話意味保持の観測 | Semantic Verifier #363 | risk policyでLLM候補 |
| Body high-level motion composition | Body Motion #338 | 必要時LLM |
| Body constraints / realtime | Solver/Controller #339/#340 | **LLMではない** |
| Memory Candidate生成 | Reflection #364 | background LLM候補 |
| Memory永続正本 | Memory Store #332 | **LLMではない** |
| Game frame-level技能 | Game Skill #365 | Skill AI方式を選択 |

重要なのは「LLMに考えさせること」と「正本状態を所有させること」を分けること。

---

## 5. Core Cognitive LLM Role候補

個数はArchitecture invariantではない。

### C01 Input Meaning

質問: **外部から何が伝えられたのか。**

自然言語→`StructuredInputMeaning`。

- 感情評価をしない
- 従うか決めない
- Goalを選ばない
- structured inputを無理に文章化しない
- bounded ReferenceContextを使う
- finite keyword/regexをopen-ended semantic fallbackにしない

### C02 Subjective Appraisal

質問: **この出来事は現在のゆらにとってどういう意味を持つか。**

同じeventでもEnergy、Desire、Relationship、Goal/Commitment、Values、Recent Experience等で評価は変わる。

LLMを使う場合も`AppraisalCandidate / StateDeltaProposal`を返し、current stateを直接上書きしない。

Deep Appraisalを毎Decisionのblocking prerequisiteにしない。

### C03 Executive Deliberation

質問: **私は今、何をしたい／何をする／何をしないか。**

唯一のconscious Goal / Action selection Authority。

入力には必要な範囲でInternal State、Memory Evidence、Relationship、`GoalContextView`、Activity/Capability/Execution facts、Turn、time/environmentを含む。

出力は`ExecutiveDecision`。Goal/Commitment transition intentを含められるが、Storeへ直接自由書込みしない。

### C04 Goal / Activity Planning

質問: **選択済みGoalをどう実行するか。**

#366の`goal_id / goal_revision`を受け、複雑Goalだけをtyped `ActivityPlan`へ分解する。

PlannerはGoalを採用・放棄・変更しない。

### C05 Speech Semantics

質問: **このSpeech Intentを実現するため何を伝えるか。**

V1の`What to say != How to say it`を維持。

`SpeechSemanticPlan`にpropositions、required/forbidden、polarity/certainty/degree、question/new-direction budget、execution truth等を閉じる。

simple speechでは専用LLMを省略可能。complex speechのみ専用Roleを起動できる。

### C06 Character Language Realization

質問: **確定済み意味を、ゆらならどう言うか。**

Characterらしさを表現するがGoal/Fact/Semantics Authorityを奪わない。

### C07 Independent Semantic Verification

質問: **CharacterUtteranceはSpeechSemanticPlanを保持しているか。**

VerifierはObserver。

- Speech Intentを変更しない
- Characterを直接指揮しない
- Runtime Factを変えない
- free-form verdictを最終Authorityにしない

final accept/rejectはtyped observation + closed policyから導出する。

required verifier待ち中もsafe Performance / speculative TTS prepを並列化可能。PASS前にexternal presentation commitはしない。

### C08 Body Motion Planning

質問: **BodyIntentをcurrent bodyからどう動いて実現するか。**

`BodyIntent + BodyState + Skeleton/DOF/limits + Expression → BodyMotionPlan`。

毎frame joint angleやrenderer固有parameterをLLMへ生成させない。deterministic solver/controllerが制約とcontinuityを所有する。

### C09 Reflection / Memory Consolidation

質問: **今回の経験から何を長期的に覚える価値があるか。**

Conversation / Stream / Game / Activity Result / State transitionsから`MemoryCandidate`を生成し、#332 Storeへ渡す。

foreground interactionをblockしないbackground責務。

---

## 6. Goal / Commitment StateはなぜLLM Roleではないか

詳細: `goal_commitment_architecture.md` / #366。

Executiveが「やりたい」と決めても、その意思が次のLLM callで消えては主体の継続性がない。

```text
Executive decision
→ validated Goal transition
→ Goal State #366
→ later CognitiveSnapshot / Autonomy trigger / Planner
```

Goal Stateは:

- goal_id / revision
- active / suspended / completed等のlifecycle
- Commitment
- priority
- completion/precondition

をtypedに保持する。

新Goalの採用/放棄AuthorityはExecutiveに残し、State ownerとDecision authorityを分離する。

これによりLLM context windowを「人格・意思の正本」にしない。

---

## 7. LLMを使わない方がよい責務

原則deterministic/typedを優先:

- Event queue / scheduler / clock
- cancellation / priority / backpressure
- schema / authority / permission checks
- Internal State reducer
- Goal / Commitment reducer
- Activity lifecycle
- Execution facts
- resource ownership
- retry / timeout policy
- Body joint limits / IK / FK / balance / interpolation
- TTS playback timing
- speech queue lifecycle
- persistence transaction
- secret handling

LLMが「成功した」と答えてもExecution Factにしない。

---

## 8. Core Cognitive AIとSkill AIを分離

### Game #365

```text
Executive Goal / Strategy
→ Game Skill Runtime
→ game-specific realtime agent
→ controller action
→ Game Result
→ Core Appraisal / Executive
```

Game AgentはLLM/VLM/RL/search/deterministic/hybridを選べるがCore Goal Authorityを持たない。frame-level actionをExecutive LLMへ毎frame問い合わせない。

### Streaming #347

大量コメント分類、moderation、clustering、summary等に専用AIを利用可能。

Skill AIは「誰へ返すか」「何を言うか」「配信を続けるか」の最終Authorityを持たない。

### Perception

Vision/audio model結果はtyped perceptとしてInput Gatewayへ返す。Perception modelがInternal Stateを直接変更しない。

---

## 9. Role分離の基準

新LLM Roleは最低限:

1. 独立した質問を1文で表現できる
2. typed input/outputがある
3. Authority重複がない
4. Unit/model evaluation可能
5. そのRoleだけ交換・改善・停止可能
6. failure/degradationを定義できる
7. deterministic処理では不足する理由がある

独立責務がないのに「賢くするため」だけでLLMを増やさない。

Roleを分けても別API callを毎回直列に行う必要はない。Provider batching/fused callを使ってもlogical contract/Authorityは維持する。

---

## 10. V1から継承する教訓

維持:

- Responsibility separation自体は良い
- Input MeaningとDecisionを分離
- `What to say` / `How to say it`を分離
- Characterへraw内部状態を解釈させない
- independent semantic verification
- finite lexical matcherをsemantic authorityにしない
- strict structured output / typed contract
- 実LLM failureをfailure classとして設計へ戻す

改善:

- LLM総数を先に制限しない
- Authorityを分散させない
- Executiveへ意味判断/計画/発話内容/表現を過剰集中しない
- Verifierをfree-form final authorityにしない
- current Goal/CommitmentをLLM Promptだけに保持しない
- long LLM/TTS/playback/Memory/Game処理を直列awaitしない

---

## 11. 自由意志に近づける必須要素

1. **User input is an event, not an unconditional command.**
2. **Persistent Internal State.** Emotion/Desire/Drive/Relationship等がturn外でも存在する。
3. **Persistent Goal / Commitment #366.** 意思がcontext windowとともに消えない。
4. **Internal autonomous triggers.** Desire/Interest/Memory/Goal/Commitment/Activity Result/time等からExecutiveを起動できる。
5. **Single Executive Authority.** Goal/Action選択の主体を分散しない。
6. **Closed experience loop.** `decide → act → actual result → appraise → state/goal/memory change → decide`。
7. **Non-blocking runtime.** この因果loopを1本のblocking Pipelineとして実装しない。

---

## 12. Design Reconciliation Status

2026-08-12時点:

- [x] 4 LLM固定を撤回
- [x] Single Executive Authorityへ統一
- [x] Goal Planning #361分離
- [x] Speech Semantics #362分離
- [x] Character Language #330をHow-to-sayへ限定
- [x] Semantic Verification #363をObserverとして分離
- [x] Appraisal #327をLLM/deterministic選択可能に変更
- [x] Reflection #364をMemory Store #332から分離
- [x] Runtime Kernel #322をnon-domain concurrent orchestrationへ一般化
- [x] Speech #348のnon-blocking invariantをCore全体へ一般化
- [x] Game Skill #365 / Streaming Skill AIをCore cognitive Authorityから分離
- [x] Persistent Goal / Commitment State #366を追加
- [x] Legacy Migration Matrixを新責務へ再マッピング

残るDesign Gate:

- [ ] subordinate canonical全体の最終整合監査
- [ ] Project sync manifest/runbookへ#366反映
- [ ] #317へDesign Reconciliation Checkpoint
- [ ] ユーザーによるV2 canonical architecture確認

製品コード実装は#317 Design Gate解除まで開始しない。
