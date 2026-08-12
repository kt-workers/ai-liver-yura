# AI Liver ゆら V2 Concurrency / LLM Invocation Architecture

Status: Draft / V2 Design Gate
System architecture: `docs/architecture/v2/system_architecture.md`
Cognitive/LLM architecture: `docs/architecture/v2/cognitive_llm_architecture.md`
Root management: #317

## 1. 目的

V2では、責務を分離してもLLM呼び出しをそのまま数珠つなぎにしない。

LLM応答待ちはCoreで最も大きな滞留要因になり得る。したがって、LLMの責務分離とRuntimeのcall graphを分けて設計する。

> **Logical Role separation != sequential LLM invocation.**

会話・Appraisal・Executive・Character・Verifier・Body・Memory等を毎回すべて順番にawaitする構造は禁止する。

---

## 2. 禁止する構造

通常会話を常に次のように処理してはならない。

```text
Input Meaning LLM
→ await
Appraisal LLM
→ await
Executive LLM
→ await
Speech Semantics LLM
→ await
Character LLM
→ await
Semantic Verifier LLM
→ await
TTS
→ playback
```

責務境界が正しくても、これでは各モデルのlatencyが加算され、V1で観測した会話間隔・待機滞留をさらに悪化させる。

---

## 3. 正規実行モデル

CoreはEvent-driven / snapshot-based / sparse activation / concurrent lanesを採用する。

```text
                         ┌─ Input / Meaning lane
                         ├─ Appraisal / State lane
Typed Event Stream ──────┼─ Executive lane
                         ├─ Speech Semantics lane
                         ├─ Character Realization lane
                         ├─ Semantic Verification lane
                         ├─ Speech Presentation lane
                         ├─ Body Realtime lane
                         ├─ Activity / Skill lanes
                         └─ Reflection / Memory lane
```

各Roleは、必要なEventが発生したときだけ起動する。

すべてのRoleを毎cycle通過させない。

---

## 4. Sparse activation

LLM Roleにはtrigger条件を持たせる。

例:

- Input Meaning: 新しいopen-ended自然言語があるときだけ
- Appraisal LLM: deterministic評価で十分でない主観的・曖昧な出来事だけ
- Executive: goal/priority/interaction decisionが必要なときだけ
- Activity Planner: 複数stepのGoalだけ
- Speech Semantics: 発話内容の組み立てが必要なときだけ
- Character: 実際に自然言語発話を準備するときだけ
- Semantic Verifier: semantic risk / production policy上必要な発話だけ、またはCharacterと並行準備
- Body Motion LLM: 新規の高レベルmotion planningが必要なときだけ
- Reflection: activity終了、idle、一定量蓄積時等

短い既知Actionやrealtime controlをLLMへ戻さない。

---

## 5. Shared Cognitive Snapshot

専門LLMを直列に手渡しするのではなく、各Roleはversion付きのtyped snapshot / read modelを読む。

```text
CognitiveSnapshot revision N
- current event / meanings
- appraisal facts
- internal state
- goals / commitments
- memory evidence
- activity facts
- capabilities
- execution facts
- turn state
- speech state
- body state summary
```

LLM結果は直接次LLMを呼ばず、typed candidate/eventとしてpublishできる。

```text
Role result
→ validate
→ publish typed event/candidate
→ interested Role may react
```

これにより、関係のないRole同士を並行実行できる。

---

## 6. Minimal critical path

ユーザーが自然言語で話しかけた場合でも、critical pathへ載せるLLMを最小化する。

### 6.1 必須依存だけを待つ

特定の入力に対する意識的判断にはInput Meaningが必要なため、その入力についてExecutiveが意味確定前に勝手に解釈してはならない。

しかし、Input Meaning待ちの間も次は止めない。

- Body realtime
- current speech playback
- Game realtime agent
- unrelated internal timer処理
- already prepared work
- input reception

### 6.2 Appraisalを常時blocking dependencyにしない

Appraisalはfast deterministic pathとdeep evaluationを分けられる。

```text
new typed event
├─ fast deterministic appraisal / existing state update
└─ optional deep Appraisal LLM (async)
```

Deep Appraisal結果が後から届いた場合はstate transitionを提案し、必要なら新しいExecutive triggerを発生させる。

「Appraisal LLMが返るまで何も考えられない」構造にはしない。

### 6.3 Planningを必要時だけ起動する

Executiveが単純なActionを選んだ場合、Activity Plannerを通さない。

複雑GoalだけをPlannerへ委譲する。

---

## 7. Speech pathの滞留対策

発話系はV1で最も滞留しやすかったため特別扱いする。

### 7.1 PresentationとPreparationを完全分離

```text
Speech A presenting
while
  next Input Meaning may run
  next Appraisal may run
  next Executive may run
  next speech may be prepared
```

音声再生完了を次generationの開始条件にしない。

### 7.2 Verifierと後処理を並列化

CharacterUtterance生成後、独立Verifierが必要な場合でも、Verifier以外の安全に先行可能な準備を並列に開始できる。

```text
CharacterUtterance
├─ Semantic Verifier
├─ TTS preparation (speculative, not yet present)
└─ Speech Performance preparation
```

Verifier PASS前に外部へ発話をcommitしないが、TTS等の準備まで待たせる必要はない。

Verifier FAILならspeculative結果を破棄する。

### 7.3 Speech SemanticsとCharacterの関係

`What to say`と`How to say it`のAuthority分離は維持する。

ただし毎回2つの大型LLMを必須直列呼び出しにはしない。

選択肢:

1. simple speechではExecutiveが十分に型付きSpeechIntent/semantic constraintsを出し、独立Speech Semantics LLMを省略する。
2. complex speechだけSpeech Semantics LLMを起動する。
3. 将来、1 provider callで複数logical outputを安全に生成できる方式を導入しても、logical authority/contractは分離したままにする。

「責務を分ける = 必ず別API callを1回ずつ直列にする」ではない。

---

## 8. Parallel fan-out

Executive Decisionが複数outputを含む場合、兄弟Realizerは可能な限り並列起動する。

```text
ExecutiveDecision
├─ Speech preparation
├─ Body planning
├─ Activity preflight/planning
└─ attention update
```

Characterが完成するまでBodyを待たせない。
Bodyが完成するまでSpeechを待たせない。

両者は同じsource_context_revisionに従う。

---

## 9. Stale result / cancellation

並行化では古いLLM結果の誤採用が新たな主要リスクになる。

各LLM request/resultは最低限以下を持つ。

```text
request_id
role_id
source_event_ids
source_context_revision
started_at
priority
interruptibility
preconditions
expires_at / stale_policy
```

commit時に現在revisionとpreconditionを確認する。

新しいuser input、Activity change、Execution failure等で前提が崩れた候補はcancel / supersede / staleにする。

長いLLM request自体も不要になった時点で可能ならcancelする。

---

## 10. Priority / backpressure

LLM request queueを無制限に増やさない。

優先例:

1. current user interaction requiring timely decision
2. safety / interruption / execution failure response
3. active Activity decision
4. autonomous speech candidate
5. reflection / memory consolidation
6. low-priority background enrichment

低優先background LLMはforeground interaction開始時に延期・cancel可能とする。

同種eventのburstはcoalesce / latest-wins / bounded queue等をRoleごとに定義する。

---

## 11. Skill AIはCore LLM待ちにしない

### Game

frame-level inputはGame Agent / RL / search / deterministic policy等が処理する。
Core Executiveは高レベルGoal/Strategy更新時だけ関与する。

### Streaming

コメント分類・moderation・summary等の大量処理は独立laneで実行する。
Coreは必要な集約eventだけ受け取る。

### Body

realtime control、blink、breath、viseme、current motion continuationはLLMを待たない。
新しい高レベルMotionPlanが届けば連続的に合流する。

---

## 12. 観測必須指標

Integration/Labで最低限以下を記録する。

- Role別 queue wait
- Role別 provider latency
- end-to-end critical path latency
- concurrent in-flight Role数
- cancellation / stale / superseded件数
- speculative work discard率
- user input arrival → Executive decision latency
- user input arrival → first speech preparation / presentation latency
- previous playback中のnext generation開始時刻
- Body frame timingへのLLM影響

平均値だけでなくp95/p99を確認する。

---

## 13. Acceptance invariant

V2 System Verificationでは最低限次を証明する。

- 1つのLLM Roleを意図的に遅延させても無関係laneは進む。
- Speech playback中に次LLM generationが開始できる。
- Appraisal deep evaluation中でも新規inputを受け取れる。
- Reflection LLM中でも通常会話できる。
- Body realtimeはLLM timeoutで停止しない。
- Game realtime agentはExecutive LLM latencyでframe loop停止しない。
- stale LLM resultが最新contextへ誤commitされない。
- background request burstでforeground user interactionがstarveしない。
