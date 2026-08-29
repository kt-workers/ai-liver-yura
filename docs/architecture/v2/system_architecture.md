# AI Liver ゆら V2 正本システムアーキテクチャ

状態: Draft / V2設計判定 / 設計再調整完了 / Streaming計画意味同期 2026-08-14  
正本branch: `rebuild/v2-foundation`  
Root: #317  
基点作業系列: `main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`  
Streaming計画意味同期: #396

## 1. 役割

AI Liver ゆら V2の最上位システム構造正本。

旧実装を継ぎ足さず、V1 Issue / PR / docs / Verificationから要求と失敗知見だけを回収し、最古mainから再構築する。

詳細正本:

- Brain: `brain_architecture.md`
- 認知 / LLM: `cognitive_llm_architecture.md`
- Goal / Commitment: `goal_commitment_architecture.md`
- 並行性: `concurrency_architecture.md`
- 発話: `speech_pipeline_architecture.md`
- Body: `body_architecture.md`
- Plugin: `plugin_architecture.md`
- Subsystem / Skill AI: `subsystem_architecture.md`
- 移行: `legacy_migration_matrix.md`
- Project同期: `project_sync_manifest.md`

---

## 2. 最終目標

**自由意志をもった「ゆら」という継続主体**を作る。

ユーザー発言への返信器ではない。

ゆらは持続する次の状態を持つ。

- 感情・欲求・駆動・動機（Emotion / Desire / Drive / Motivation）
- 価値観・道徳文脈（Values / Moral context）
- 興味・好奇心（Interest / Curiosity）
- 関係性（Relationship）
- 記憶（Memory）
- 現在Goal / Commitment
- 注意・焦点・Turn状態（Attention / Focus / Turn state）
- 現在Activity / 実実行状態
- Body State

外界と自身の変化を受けながら、会話、YouTube配信、ゲーム対戦・実況、観察、沈黙などを自ら選択する。

ユーザー発言は重要Eventだが無条件命令ではない。

「ゆらが配信する」「ゆらがゲームをする」などの主体性はCoreのGoal / Activity正本で表現し、外部サービス固有実装をCoreへ持ち込むことでは表現しない。

---

## 3. システム境界

```text
AI Liver Yura
├─ Core
│  ├─ Brain
│  ├─ Body
│  └─ Plugin Architecture
├─ Infrastructure / Providers
└─ Subsystems / Skill Runtimes
   ├─ Avatar
   ├─ Streaming
   ├─ Game Skill
   ├─ GUI/Admin
   ├─ Validation Labs
   └─ Development Tooling
```

Core所属を実行時の任意性だけで決めない。

Core正本例:

- Brain認知
- Internal State
- Executive正本
- Goal / Commitment State #366
- Attention / Focus / Turn State #333
- Body / Body State
- Plugin拡張契約

Avatar不在でもBodyはPluginにならない。Persistence不在でもGoal / MemoryのDomain所有権はInfrastructureへ移らない。

---

## 4. クリーンアーキテクチャ

```text
Domain / Contracts
        ↑
Application / Use Cases
        ↑
Ports
        ↑
Adapters / Providers / UI / External systems
```

DomainはOpenAI SDK、FastAPI、VOICEVOX、PostgreSQL、Live2Dなどの具体型を知らない。Infrastructure ProviderはPluginではない。

外部サービス固有のSDK、protocol、credential、resource IDをCore Domain / Runtimeへ持ち込まない。

---

## 5. Plugin境界

Pluginを任意性だけで定義しない。

> **PluginはCore自身の構成要素ではなく、Core公開拡張契約から外部利用能力（Capability）を追加する機構である。**

Core固有State / Authorityを所有しない。`Plugin 0件でもCore基本責務維持`は別のシステム不変条件とする。

---

## 6. Subsystem / Skill AI境界

Subsystemは独立したライフサイクル、process、resource所有権を持てる。

専門AIは「選択済みActivityを実行する技能」であり、ゆらの意思そのものではない。

- Game Agent
- Streaming分類・moderation・aggregation
- Vision / recognition

Skill AIはExecutive Goal正本を奪わない。

### 6.1 Core判断 / Subsystem実行 / 外界観測

外部サービスを伴うActivityでは3つの正本責務を分ける。

```text
Core Executive
  ゆらが何をするか決める
        ↓
汎用Activity / Capability Request
        ↓
Subsystem
  提供元固有操作を実行する
        ↓
Execution Result / External Observation
        ↓
Core
  実結果を認識して再評価する
```

Coreは配信準備、配信開始、配信終了などの高水準Activityを選択できる。

ただしYouTube API、OBS WebSocket、OAuth、提供元固有IDやsceneなどはStreaming Subsystem側だけが所有する。Core本番コードはYouTube / OBSなどの提供元固有class、port、runtime責務を持たない。

外界状態はSubsystem / API観測だけでなくユーザー報告などからも認知できる。情報源、出自、確信度（source / provenance / confidence）を保持し、報告と提供元確認済み事実を無条件に同一視しない。

IntentやCharacter発話は外部操作成功Factではない。Actual Factは信頼済みExecution Result / Observationで確定する。

---

## 7. 認知因果モデル

```text
External / Internal Events
→ Perception / Input Meaning
→ Subjective Appraisal / salience
→ Internal State
→ Attention / Focus eligibility
→ Executive Deliberation
→ Goal / Commitment transition
→ Persistent Goal / Commitment State
→ Planning / Realization / Execution
→ Actual Result / New Events
→ Appraisal / Attention / Executive / Goal / Reflection / Memory
```

これは因果図であり、固定された直列停止処理ではない。

---

## 8. 実行モデル

- Event駆動
- snapshot基準
- 必要時だけ活性化
- 並行処理系統
- 上限付きqueue
- 優先度 / backpressure
- cancellation / stale / supersede
- `source_context_revision`
- 必要箇所で`goal_revision` / `attention_revision`

```text
                         ┌─ Input / Meaning
                         ├─ Appraisal / State
Typed Event Stream ──────┼─ Attention / Turn
                         ├─ Executive
                         ├─ Goal State / Planning
                         ├─ Speech Preparation
                         ├─ Speech Presentation
                         ├─ Body Realtime
                         ├─ Skill / Subsystem
                         └─ Reflection / Persistence
```

必須:

- 遅いLLM処理中も無関係な系統を継続する。
- 発話再生中に次の認知・生成を実行できる。
- TTS待機中に新しい入力を受けられる。
- Goal / Focus変更をCore全体lockにしない。
- Body実時間処理はLLM / TTS / DB / Game AI待ちで停止しない。
- Reflectionは前景対話を停止させない。
- Game frame loopはExecutive LLM遅延に依存しない。
- Streaming大量入力でCoreを飢餓状態にしない。
- 背景処理が前景対話を飢餓状態にしない。

Subsystemの外部API待ちをCore Runtimeの専用配信処理として抱え込まず、汎用非同期Capability / Event境界で隔離する。

---

## 9. LLM設計

旧システム全体4-role固定は撤回する。LLM個数をアーキテクチャ不変条件にしない。

初期役割候補:

- 入力意味解析（Input Meaning）
- 主観評価（Subjective Appraisal、必要時）
- Executive熟考（Executive Deliberation）
- Goal / Activity計画
- 発話意味（Speech Semantics）
- Character Language
- 独立意味検証（Independent Semantic Verification）
- Body動作計画（Body Motion Planning）
- Reflection

ただし:

> **意識的なGoal / Action正本 = Executive #328だけ**

Goal State #366、Attention #333、State Reducer、Activity / Execution、Body物理・実時間処理などは型付き決定論的所有を基本とする。

`Logical Role != API Call`。責務分離を直列の提供元呼出し鎖へ変換しない。

---

## 10. システム正本対応表

| 正本責務 | 所有者 |
|---|---|
| 開かれた自然言語意味 | #326 |
| 主観評価・重要度候補 | #327 |
| 現在Internal State | #327 State Reducer |
| 意識的Goal / Action選択 | #328 Executive |
| 現在Goal / Commitment | #366 |
| 現在Attention / Focus / Turn割当 | #333 |
| 複雑Goal計画 | #361 |
| Activityライフサイクル / Actual Fact | #329 |
| 何を言うか | #362 |
| どう言うか | #330 |
| 意味観測 | #363 |
| 発話演技 / 提示 | #331/#348 |
| Body現在状態 / 物理的連続性 | #335〜#341 |
| Memory正本保存 / 検索 | #332 |
| Memory候補生成 | #364 |
| Game frame単位の技能 | #365、Core Goalに従属 |
| Streaming提供元実行 / 観測 | #347 Subsystem、Core Activityに従属 |

LLM自由文をState / Factへ直接代入しない。Intent / Plan / Character claimをActual Factへ昇格させない。

---

## 11. 永続Goal / Commitment — #366

```text
Executive chooses Goal
→ validated transition
→ Goal State
→ later Attention / Executive / Planner
```

- turn / context windowをまたぐ。
- GoalとActivityを分離する。
- GoalとMemoryを分離する。
- CommitmentとCharacter utteranceを分離する。
- 古い`goal_revision`のPlanを実行しない。
- 未完了Goal / Commitmentが自律起動条件になり得る。

---

## 12. Attention / Focus / Turn — #333

Game、Streaming、Conversation、Reflectionなどの全EventをExecutiveへ同期投入しない。

```text
Game realtime             → Skill aggregation
Streaming burst           → aggregation
User direct speech        → high priority
Reflection                → background
         ↓
#333 Focus / Turn scheduling
         ↓ eligible trigger / AttentionFocusView
Executive
```

#333が所有するもの:

- 前景Focus
- 副次監視
- Turn / 応答義務
- Attention / 情報源budget
- 割込みしきい値
- 公平性 / 飢餓防止

Appraisalは重要度候補、Executiveは意識的な注意意図、#333はFocus State / schedulingを所有する。意味、Goal、発話内容は決めない。Body gazeはFocusの表現であり認知正本ではない。

---

## 13. 発話概要

```text
Executive SpeechIntent
→ SpeechSemanticPlan       # 何を言うか
→ CharacterUtterance       # どう言うか
→ Semantic Observation
→ closed acceptance
→ Performance / Prepared candidate
→ Presentation
```

論理依存関係を固定直列LLM呼出し鎖にしない。

- 単純な意味経路では専用LLMを省略できる。
- Character後のVerifier / Performance / 安全なTTS準備を並行実行できる。
- 必須`PASS`前に外部提示を確定しない。
- Speech A再生中にSpeech Bを生成できる。
- context / goal / attention revisionで提示直前再検証する。

---

## 14. Body概要

- 正本Skeleton / DOF / limits
- 現在pose / velocity
- Expression投影
- Motion Planning（必要時だけLLM）
- 決定論的IK / FK / balance / trajectory
- 連続Controller
- gaze / blink / breath / viseme / 微細実時間処理
- `BodyPoseFrame`

固定presetを主経路にせず、現在poseの連続性を維持しHomeへ強制resetしない。Motion Plannerが遅延しても実時間処理を停止しない。CharacterとBodyはExecutiveから兄弟関係として分岐する。

---

## 15. Streaming / Game概要

### Streaming #347

Streamingは**Core内の配信Moduleではなく独立Subsystem**である。

Coreが所有するもの:

- 配信を準備・開始・継続・終了するかというActivity / Goal判断
- 視聴者commentへ反応するか
- 何を言うか

Streaming Subsystemが所有するもの:

- 提供元固有の準備確認・prepare / start / end実行
- YouTube / OBSなどのAPI、protocol、authentication
- 配信状態 / healthの提供元観測
- comment取込、集約、backpressure
- 提供元結果の型付きExecution Result / External Observation化

```text
User / Internal Goal
→ Input / Executive
→ generic Capability Request
→ Streaming Subsystem
→ external provider operation
→ Execution Result / Observation
→ Appraisal / Attention / Executive
```

OBS profile、scene graph、encoderなどの構成は原則事前準備し、任意構成の自動生成を#347の必須責務にしない。

API観測がなくても、ユーザーから配信開始済みなどの状態報告を受けて認知候補にできる。ただし`user_report`の出自を保持し、提供元確認済みFactと区別する。

### Game #365

```text
Core Executive / Goal State
→ High-level Strategy
→ Game Skill Runtime
→ realtime agent
→ controller
→ salient Event / Result
→ Appraisal / Attention / Executive
```

Game Agentが実況台詞を直接発話しない。

---

## 16. 自然言語方針

開かれた意味の正本として、有限keyword、marker、regex、substring、`startswith`などを使わない。

自然言語の設計文書、Issue、テストに記載する文言は原則として**意味カテゴリの説明または例示**であり、その文字列自体をtrigger、allowlist、matcher仕様にしてはならない。

例えば外部Activityは「配信開始を求める旨を伝える」「配信が開始済みである旨を報告する」のように意味で記述する。実装・検証では同義表現、語順差、敬語、口語、省略、文脈参照を含む言い換え（paraphrase）で同じ`StructuredInputMeaning`へ一般化できることを確認する。

開かれた自然言語意味の正本は#326 Input Meaningだけとする。Streaming Subsystem、Executive、Activity Runtime、Provider Adapterが生の自然言語をkeyword / regex / substringで再解釈しない。

protocol token、enum、厳密technical ID、有限領域語彙は例外とする。解決不能はunresolved / clarification / fail-closedとする。

---

## 17. 実行事実

```text
requested → accepted → planned → started → observable/applied → completed
or rejected / unsupported / failed / cancelled / timed_out / superseded
```

```text
I want X        → internal/goal semantic
I decided X     → Executive / Goal transition
I am doing X    → Activity/Execution Fact
I did X         → completed Fact
I promised X    → Commitment State
I said promise  → Speech Presentation Fact
```

外部Subsystem操作も同じ真実境界に従う。配信開始Intentを持ったことと、提供元上で実際にliveになったことを分離する。

---

## 18. Character / Body / Skillの兄弟境界

```text
                    ExecutiveDecision
                  /        |          \
          SpeechIntent   BodyIntent   Activity/Goal
              ↓             ↓             ↓
          Speech path    Body path    Plugin/Subsystem
```

Character textからBody semantic commandを作らない。Body poseからSpeech meaningを決めない。Skill AIからCore Goalを作らない。Subsystem Execution Resultからのみ外部実行Factを確定し、Character claimから逆算しない。

---

## 19. Memory / Reflection

- #364 Reflection: 開かれた`MemoryCandidate`
- #332 Memory Store: validation / store / retrieval
- #359 Persistence Provider: 実装

Memoryは現在Internal State / Goal State / Execution Factより強い正本性を持たない。

---

## 20. Module開発判定

```text
Canonical Design
→ Work Issue
→ Unit Acceptance
→ implementation lineage / Draft PR
→ Unit PASS
→ Adjacent PASS
→ Integration
→ User Verification if required
→ Done
```

1 Work Issueにつき有効な実装作業系列は1本とする。

---

## 21. 設計再調整状態

設計反映とIssue整合監査は完了済み。

- [x] System / Brain / Cognitive / Goal / Concurrency正本
- [x] Speech / Body / Plugin / Subsystem正本
- [x] Legacy 44 Open Issue / initial 23 PRの要件対応付け
- [x] 可変LLM / Single Executive
- [x] 非直列LLM / runtime
- [x] 永続Goal #366
- [x] Attention / Focus #333
- [x] Game / Streaming Skill AI境界
- [x] Plugin構造定義
- [x] 現在V2 Issueからactive Commander / fixed Role番号を排除
- [x] 従属正本 / Issue横断監査
- [x] Project同期Manifest / Runbook
- [x] #394 StreamingのCore判断 / Subsystem実行 / 外界観測境界を再調整
- [x] #396 Streaming実装計画と自然言語の意味・言い換え原則を同期

#319の実GitHub Projects v2 field / 正式Parent-Subissue変更は現実行環境の制約により別途`Blocked`管理する。
