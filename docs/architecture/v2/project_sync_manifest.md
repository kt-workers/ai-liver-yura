# AI Liver ゆら V2 GitHub Projects Sync Manifest

Status: Draft / #319 / Canonical values resolved 2026-08-13
Project: `ktan514 / 6`
Root: #317
Canonical: `docs/architecture/v2/system_architecture.md`
Runbook: `docs/architecture/v2/project_sync_runbook.md`

Related canonicals:
- `brain_architecture.md`
- `cognitive_llm_architecture.md`
- `goal_commitment_architecture.md`
- `concurrency_architecture.md`
- `speech_pipeline_architecture.md`
- `body_architecture.md`
- `plugin_architecture.md`
- `subsystem_architecture.md`
- `legacy_migration_matrix.md`

## 1. 目的

V2 Issue hierarchyをGitHub Projects v2「プロジェクトゆら」へ同期する正本。

Project field / formal Sub-issue操作前にGitHub liveからfield ID / option ID / item IDを取得し、旧Snapshot IDを推測利用しない。

実行手順・STOP条件は`project_sync_runbook.md`。

---

## 2. Design Gate Status Policy

- #317: `In progress`
- #318: `In progress`
- #319: `Blocked`
- Product/Design Work・Parent・Integration: 原則`Blocked` by #317

ユーザーがV2 canonical designを明示確認するまでproduct implementation issueを`In progress`へしない。

---

## 3. `作業種別` canonical rule

`作業種別`は現在の進捗段階ではなく、**Issueの主成果物**を表すsingle-selectとして固定する。

利用する既存Option:

- `設計`: Architecture / Parent設計が主成果物
- `実装`: Product / Runtime / Provider / UI / Toolの実装が主成果物
- `検証`: Integration / Validation / System Verificationが主成果物
- `調査`: Inventory / Migration / Project監査・同期など管理調査が主成果物
- `ドキュメント`: 人間向け正本文書そのものが主成果物
- `不具合`: 今回のV2新体系では対象なし

同一Issueで設計→実装→Verificationと進んでも`作業種別`を工程ごとに変更しない。進捗は`Status`で管理する。

特殊ケース:
- #317 = `設計`
- #318 = `調査`
- #319 = `調査`
- Parent = 原則`設計`
- Integration = 原則`検証`
- #352 Validation Labs = `検証`
- #354 Character Bible = `ドキュメント`
- その他のProduct Work = 原則`実装`

---

## 4. `領域` canonical taxonomy

`領域`は詳細Module階層を複製しない。**Project上での広い分類**に限定する。
詳細責務はformal Parent/Sub-issue hierarchyとIssue本文で表現する。

### 既存Optionを継続利用

- `Core`
- `入力意味解析`
- `内部指示器`（Legacy用。V2新Issueでは原則使用しない）
- `感情・欲望・善悪`
- `Body`
- `Avatar／Live2D`
- `GUI`
- `Memory`
- `Infrastructure`

### V2で追加するOption

- `Management`
- `Character`
- `Plugin`
- `Subsystem`
- `Streaming`
- `Game`
- `Validation`
- `System Integration`

旧Optionは削除・renameしない。
V2同期では不足する上記8 Optionだけをexisting `領域` fieldへ非破壊追加する。

---

## 5. Parent / Sub-issue hierarchy

```text
#317 V2 Root
├─ #318 Migration Matrix [Management]
├─ #319 Project Sync [Management]
├─ #320 Core Foundation [Parent]
│  ├─ #321 Typed Contracts
│  ├─ #322 Runtime Kernel / Concurrency
│  ├─ #323 Variable LLM Role / Invocation Contracts
│  └─ #324 Character Definition [Parent]
│     ├─ #354 Character Bible
│     └─ #355 Character Projection
├─ #325 Brain [Parent]
│  ├─ #349 Input Gateway
│  ├─ #326 Input Meaning
│  ├─ #327 Appraisal / Internal State
│  ├─ #328 Executive Deliberation
│  ├─ #366 Goal / Commitment State
│  ├─ #361 Goal / Activity Planning
│  ├─ #329 Activity Execution
│  ├─ #362 Speech Semantics
│  ├─ #330 Character Language
│  ├─ #363 Semantic Verification
│  ├─ #331 Speech Performance
│  ├─ #348 Speech Pipeline
│  ├─ #332 Memory Store / Retrieval
│  ├─ #364 Reflection / Consolidation
│  ├─ #333 Attention / Autonomy / Turn
│  └─ #334 Brain Integration
├─ #335 Body [Parent]
│  ├─ #336 Canonical Body Model
│  ├─ #337 Body Expression
│  ├─ #338 Body Motion Planner
│  ├─ #339 Solver / Controller
│  ├─ #340 Realtime Layers
│  └─ #341 Body Integration
├─ #342 Plugin Architecture [Parent]
│  ├─ #343 Registry / Manifest / Lifecycle
│  └─ #344 Plugin Integration
├─ #350 Core Lifecycle / Graceful Degradation
├─ #356 Infrastructure [Parent]
│  ├─ #357 LLM Provider
│  ├─ #358 TTS Provider
│  └─ #359 Persistence Provider
├─ #345 Subsystems [Parent]
│  ├─ #346 Avatar
│  ├─ #347 Streaming
│  ├─ #365 Game Skill
│  ├─ #351 GUI / Admin
│  ├─ #352 Validation / Concurrency Labs
│  └─ #353 Development Tooling
└─ #360 System Integration
```

---

## 6. Project Items / canonical field values

| 工程 | Issue | Level | 作業種別 | 領域 | 優先度 | Start | Target | Gate Status |
|---:|---:|---|---|---|---|---|---|---|
| 0 | #317 | Management/Root | 設計 | Management | Critical | 2026-08-12 | 2026-10-31 | In progress |
| 10 | #318 | Management | 調査 | Management | Critical | 2026-08-12 | 2026-08-16 | In progress |
| 20 | #319 | Management | 調査 | Management | Critical | 2026-08-12 | 2026-08-17 | Blocked |
| 100 | #321 | Work | 実装 | Core | Critical | 2026-08-13 | 2026-08-15 | Blocked |
| 110 | #322 | Work | 実装 | Core | Critical | 2026-08-15 | 2026-08-21 | Blocked |
| 120 | #323 | Work | 実装 | Core | Critical | 2026-08-15 | 2026-08-20 | Blocked |
| 130 | #320 | Parent | 設計 | Core | Critical | 2026-08-13 | 2026-08-26 | Blocked |
| 140 | #354 | Work | ドキュメント | Character | Critical | 2026-08-17 | 2026-08-21 | Blocked |
| 150 | #355 | Work | 実装 | Character | Critical | 2026-08-21 | 2026-08-24 | Blocked |
| 160 | #324 | Parent | 設計 | Character | Critical | 2026-08-17 | 2026-08-24 | Blocked |
| 170 | #357 | Work | 実装 | Infrastructure | Critical | 2026-08-18 | 2026-08-27 | Blocked |
| 200 | #349 | Work | 実装 | 入力意味解析 | Critical | 2026-08-19 | 2026-08-23 | Blocked |
| 210 | #326 | Work | 実装 | 入力意味解析 | Critical | 2026-08-19 | 2026-08-24 | Blocked |
| 220 | #327 | Work | 実装 | 感情・欲望・善悪 | Critical | 2026-08-24 | 2026-08-31 | Blocked |
| 230 | #328 | Work | 実装 | Core | Critical | 2026-08-31 | 2026-09-06 | Blocked |
| 235 | #366 | Work | 実装 | Core | Critical | 2026-09-04 | 2026-09-09 | Blocked |
| 240 | #361 | Work | 実装 | Core | Critical | 2026-09-06 | 2026-09-11 | Blocked |
| 250 | #329 | Work | 実装 | Core | Critical | 2026-09-05 | 2026-09-10 | Blocked |
| 260 | #362 | Work | 実装 | Core | Critical | 2026-09-06 | 2026-09-11 | Blocked |
| 270 | #330 | Work | 実装 | Character | Critical | 2026-09-10 | 2026-09-15 | Blocked |
| 280 | #363 | Work | 実装 | Core | Critical | 2026-09-12 | 2026-09-17 | Blocked |
| 290 | #331 | Work | 実装 | Core | High | 2026-09-14 | 2026-09-17 | Blocked |
| 300 | #348 | Work | 実装 | Core | Critical | 2026-09-17 | 2026-09-23 | Blocked |
| 310 | #332 | Work | 実装 | Memory | High | 2026-09-15 | 2026-09-22 | Blocked |
| 320 | #364 | Work | 実装 | Memory | High | 2026-09-18 | 2026-09-24 | Blocked |
| 330 | #333 | Work | 実装 | Core | High | 2026-09-20 | 2026-09-26 | Blocked |
| 340 | #350 | Work | 実装 | Core | Critical | 2026-09-18 | 2026-09-25 | Blocked |
| 350 | #358 | Work | 実装 | Infrastructure | High | 2026-09-22 | 2026-09-27 | Blocked |
| 360 | #359 | Work | 実装 | Infrastructure | High | 2026-09-22 | 2026-09-28 | Blocked |
| 370 | #334 | Integration | 検証 | Core | Critical | 2026-09-25 | 2026-10-02 | Blocked |
| 380 | #325 | Parent | 設計 | Core | Critical | 2026-08-19 | 2026-10-05 | Blocked |
| 400 | #336 | Work | 実装 | Body | Critical | 2026-09-01 | 2026-09-07 | Blocked |
| 410 | #337 | Work | 実装 | Body | Critical | 2026-09-07 | 2026-09-12 | Blocked |
| 420 | #338 | Work | 実装 | Body | Critical | 2026-09-12 | 2026-09-19 | Blocked |
| 430 | #339 | Work | 実装 | Body | Critical | 2026-09-18 | 2026-09-26 | Blocked |
| 440 | #340 | Work | 実装 | Body | High | 2026-09-26 | 2026-10-01 | Blocked |
| 450 | #341 | Integration | 検証 | Body | Critical | 2026-10-01 | 2026-10-08 | Blocked |
| 460 | #335 | Parent | 設計 | Body | Critical | 2026-09-01 | 2026-10-08 | Blocked |
| 500 | #343 | Work | 実装 | Plugin | Critical | 2026-09-10 | 2026-09-18 | Blocked |
| 510 | #344 | Integration | 検証 | Plugin | Critical | 2026-09-30 | 2026-10-05 | Blocked |
| 520 | #342 | Parent | 設計 | Plugin | Critical | 2026-09-10 | 2026-10-05 | Blocked |
| 530 | #356 | Parent | 設計 | Infrastructure | High | 2026-08-18 | 2026-09-28 | Blocked |
| 600 | #347 | Work | 実装 | Streaming | High | 2026-10-01 | 2026-10-12 | Blocked |
| 610 | #352 | Work | 検証 | Validation | High | 2026-10-01 | 2026-10-16 | Blocked |
| 620 | #353 | Work | 実装 | Validation | Medium | 2026-10-05 | 2026-10-18 | Blocked |
| 630 | #346 | Work | 実装 | Avatar／Live2D | High | 2026-10-08 | 2026-10-15 | Blocked |
| 640 | #351 | Work | 実装 | GUI | High | 2026-10-08 | 2026-10-18 | Blocked |
| 645 | #365 | Work | 実装 | Game | High | 2026-10-08 | 2026-10-20 | Blocked |
| 650 | #345 | Parent | 設計 | Subsystem | High | 2026-09-30 | 2026-10-20 | Blocked |
| 700 | #360 | Integration | 検証 | System Integration | Critical | 2026-10-20 | 2026-10-31 | Blocked |

---

## 7. Architecture invariants in Project

- variable LLM Role count
- Single Executive Authority
- current Goal/Commitment = #366
- current Attention/Focus/Turn = #333
- `Logical Role != API Call`
- no serial LLM chain as default
- source_context_revision / goal_revision / attention_revision
- foreground > low-priority background
- Speech playback中next generation
- Body realtime independent from LLM waits
- Game frame loop independent from Executive LLM
- Streaming burst isolation
- Plugin structural definition, not optionality-only

---

## 8. Sync Rule

1. Runbookに従いProject #6 live取得
2. field/option/item IDs取得
3. V2追加Area 8 Optionを非破壊で確認/追加
4. `作業種別`を本Manifestの一意値で解決
5. duplicate item確認
6. #361〜#366 existence確認
7. formal Parent/Sub-issue確認
8. Manifestとの差分dry-run
9. canonical一致時のみmutation
10. mutation後再取得監査

古いIDを推測しない。既存Area optionはこの同期作業では削除・renameしない。

---

## 9. Completion

- [x] V2 logical hierarchy
- [x] #361〜#366作成
- [x] Start/Target Issue本文設定
- [x] Design Gate status policy
- [x] broad Area taxonomy確定
- [x] V2追加Area Optionを8個へ限定
- [x] 50 Issueの`作業種別`一意値確定
- [x] Area / 工程 / Priority / Schedule正本
- [x] variable LLM / non-serial runtime
- [x] Game Skill
- [x] persistent Goal State
- [x] Attention/Focus #333 metadata
- [x] live-ID/dry-run/mutation/re-audit runbook
- [ ] missing V2 Area optionsをProjectへ非破壊追加
- [ ] V2 Issue project一意登録確認
- [ ] Status/作業種別/領域/優先度/工程/Start/Target同期
- [ ] formal Parent/Sub-issue同期
- [ ] re-audit PASS
