# AI Liver ゆら V2 GitHub Projects Sync Manifest

Status: Draft / #319
Project: `ktan514 / 6`
Root: #317
Canonical architecture: `docs/architecture/v2/system_architecture.md`
Brain: `docs/architecture/v2/brain_architecture.md`
Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Migration: `docs/architecture/v2/legacy_migration_matrix.md`

## 1. 目的

V2 Issue hierarchyをGitHub Projects v2「プロジェクトゆら」へ同期するための一括正本。

ChatGPT GitHub ConnectorではProjects v2 field mutation / GitHub正式Sub-issue mutationを直接実行できない場合があるため、本Manifestで値を先に確定し、実行可能な環境で同期する。

同期時はProject field ID / option ID / item IDをGitHub liveから再取得し、古いSnapshot IDを推測で使用しない。

---

# 2. Design Gate中のStatus policy

現在は#317 V2 Design Gate中。

| 対象 | Status |
|---|---|
| #317 | In progress |
| #318 | In progress（mapping完了、legacy closeはDesign承認待ち） |
| #319 | Blocked（Projects/Sub-issue mutation実行可能環境待ち） |
| #320〜#364のproduct/design Work/Parent/Integration | Blocked by #317 Design Gate |

ユーザーがV2 canonical designを確認するまで、未来Start dateが近くても製品実装IssueをIn progressへしない。

Design Gate解除後、工程順に依存を再確認してReadyへ移す。

---

# 3. Project field schema for V2

## Status

- Backlog
- Ready
- In progress
- Review
- Verification
- Blocked
- Done

## Issueレベル

- Parent
- Work
- Integration
- Management

## 作業種別

- 設計
- 実装
- 検証
- 調査
- 不具合
- ドキュメント

## 優先度

| Issue priority | Project priority |
|---|---|
| P0 | Critical |
| P1 | High |
| P2 | Medium |
| P3 | Low |

## 領域

V2推奨Area:

- Management
- Core / Foundation
- Core / Character Definition
- Core / Brain / Input
- Core / Brain / Appraisal
- Core / Brain / Executive
- Core / Brain / Goal Planning
- Core / Brain / Activity
- Core / Brain / Speech Semantics
- Core / Brain / Character Language
- Core / Brain / Semantic Verification
- Core / Brain / Speech Runtime
- Core / Brain / Memory
- Core / Brain / Reflection
- Core / Brain / Autonomy
- Core / Body
- Core / Plugin
- Infrastructure / LLM
- Infrastructure / TTS
- Infrastructure / Persistence
- Subsystem / Avatar
- Subsystem / Streaming
- Subsystem / GUI
- Subsystem / Validation
- Subsystem / Tooling
- System Integration

旧Area optionはlegacy item整理前に削除しない。

---

# 4. GitHub正式Parent/Sub-issues manifest

```text
#317 V2 Root
├─ #318 Migration Matrix [Management]
├─ #319 Project Sync [Management]
├─ #320 Core Foundation [Parent]
│  ├─ #321 Typed Contracts [Work]
│  ├─ #322 Runtime Kernel / Concurrency [Work]
│  ├─ #323 Variable LLM Role / Invocation Contracts [Work]
│  └─ #324 Character Definition [Parent]
│     ├─ #354 Character Bible [Work]
│     └─ #355 Character Projection [Work]
├─ #325 Brain [Parent]
│  ├─ #349 Input Gateway [Work]
│  ├─ #326 Input Meaning [Work]
│  ├─ #327 Subjective Appraisal / Internal State [Work]
│  ├─ #328 Executive Deliberation [Work]
│  ├─ #361 Goal / Activity Planning [Work]
│  ├─ #329 Activity Execution [Work]
│  ├─ #362 Speech Semantics [Work]
│  ├─ #330 Character Language [Work]
│  ├─ #363 Semantic Verification [Work]
│  ├─ #331 Speech Performance [Work]
│  ├─ #348 Speech Pipeline [Work]
│  ├─ #332 Memory Store / Retrieval [Work]
│  ├─ #364 Reflection / Consolidation [Work]
│  ├─ #333 Autonomy / Turn [Work]
│  └─ #334 Brain Integration [Integration]
├─ #335 Body [Parent]
│  ├─ #336 Canonical Body Model [Work]
│  ├─ #337 Body Expression [Work]
│  ├─ #338 Body Motion Planner [Work]
│  ├─ #339 Solver / Controller [Work]
│  ├─ #340 Realtime Layers [Work]
│  └─ #341 Body Integration [Integration]
├─ #342 Plugin Architecture [Parent]
│  ├─ #343 Registry / Manifest / Lifecycle [Work]
│  └─ #344 Plugin Integration [Integration]
├─ #350 Core Lifecycle / Graceful Degradation [Work]
├─ #356 Infrastructure Adapters [Parent]
│  ├─ #357 Variable LLM Provider [Work]
│  ├─ #358 TTS Provider [Work]
│  └─ #359 Persistence Provider [Work]
├─ #345 Subsystems [Parent]
│  ├─ #346 Avatar [Work]
│  ├─ #347 Streaming [Work]
│  ├─ #351 GUI / Admin [Work]
│  ├─ #352 Validation / Concurrency Labs [Work]
│  └─ #353 Development Tooling [Work]
└─ #360 System Integration [Integration]
```

本文`Parent:`とGitHub正式Parent/Sub-issuesを一致させる。

---

# 5. V2 Project items

`工程`は小さいほど先。番号間隔はIssue追加余地を残す。

| 工程 | Issue | Level | Type | Area | Priority | Start | Target | Design Gate中Status |
|---:|---:|---|---|---|---|---|---|---|
| 0 | #317 | Management / Root Parent | 設計 | Management | Critical | 2026-08-12 | 2026-10-31 | In progress |
| 10 | #318 | Management | 調査 | Management | Critical | 2026-08-12 | 2026-08-15 | In progress |
| 20 | #319 | Management | 調査 | Management | Critical | 2026-08-12 | 2026-08-16 | Blocked |
| 100 | #321 | Work | 実装 | Core / Foundation | Critical | 2026-08-13 | 2026-08-15 | Blocked |
| 110 | #322 | Work | 実装 | Core / Foundation | Critical | 2026-08-15 | 2026-08-21 | Blocked |
| 120 | #323 | Work | 実装 | Core / Foundation | Critical | 2026-08-15 | 2026-08-20 | Blocked |
| 130 | #320 | Parent | 設計 | Core / Foundation | Critical | 2026-08-13 | 2026-08-26 | Blocked |
| 140 | #354 | Work | ドキュメント | Core / Character Definition | Critical | 2026-08-17 | 2026-08-21 | Blocked |
| 150 | #355 | Work | 実装 | Core / Character Definition | Critical | 2026-08-21 | 2026-08-24 | Blocked |
| 160 | #324 | Parent | 設計 | Core / Character Definition | Critical | 2026-08-17 | 2026-08-24 | Blocked |
| 170 | #357 | Work | 実装 | Infrastructure / LLM | Critical | 2026-08-18 | 2026-08-27 | Blocked |
| 200 | #349 | Work | 実装 | Core / Brain / Input | Critical | 2026-08-19 | 2026-08-23 | Blocked |
| 210 | #326 | Work | 実装 | Core / Brain / Input | Critical | 2026-08-19 | 2026-08-24 | Blocked |
| 220 | #327 | Work | 実装 | Core / Brain / Appraisal | Critical | 2026-08-24 | 2026-08-31 | Blocked |
| 230 | #328 | Work | 実装 | Core / Brain / Executive | Critical | 2026-08-31 | 2026-09-06 | Blocked |
| 240 | #361 | Work | 実装 | Core / Brain / Goal Planning | Critical | 2026-09-06 | 2026-09-11 | Blocked |
| 250 | #329 | Work | 実装 | Core / Brain / Activity | Critical | 2026-09-05 | 2026-09-10 | Blocked |
| 260 | #362 | Work | 実装 | Core / Brain / Speech Semantics | Critical | 2026-09-06 | 2026-09-11 | Blocked |
| 270 | #330 | Work | 実装 | Core / Brain / Character Language | Critical | 2026-09-10 | 2026-09-15 | Blocked |
| 280 | #363 | Work | 実装 | Core / Brain / Semantic Verification | Critical | 2026-09-12 | 2026-09-17 | Blocked |
| 290 | #331 | Work | 実装 | Core / Brain / Speech Runtime | High | 2026-09-14 | 2026-09-17 | Blocked |
| 300 | #348 | Work | 実装 | Core / Brain / Speech Runtime | Critical | 2026-09-17 | 2026-09-22 | Blocked |
| 310 | #332 | Work | 実装 | Core / Brain / Memory | High | 2026-09-15 | 2026-09-22 | Blocked |
| 320 | #364 | Work | 実装 | Core / Brain / Reflection | High | 2026-09-18 | 2026-09-24 | Blocked |
| 330 | #333 | Work | 実装 | Core / Brain / Autonomy | High | 2026-09-20 | 2026-09-25 | Blocked |
| 340 | #350 | Work | 実装 | Core / Foundation | Critical | 2026-09-18 | 2026-09-25 | Blocked |
| 350 | #358 | Work | 実装 | Infrastructure / TTS | High | 2026-09-22 | 2026-09-27 | Blocked |
| 360 | #359 | Work | 実装 | Infrastructure / Persistence | High | 2026-09-22 | 2026-09-28 | Blocked |
| 370 | #334 | Integration | 検証 | System Integration | Critical | 2026-09-25 | 2026-10-02 | Blocked |
| 380 | #325 | Parent | 設計 | Core / Brain / Executive | Critical | 2026-08-19 | 2026-10-05 | Blocked |
| 400 | #336 | Work | 実装 | Core / Body | Critical | 2026-09-01 | 2026-09-07 | Blocked |
| 410 | #337 | Work | 実装 | Core / Body | Critical | 2026-09-07 | 2026-09-12 | Blocked |
| 420 | #338 | Work | 実装 | Core / Body | Critical | 2026-09-12 | 2026-09-19 | Blocked |
| 430 | #339 | Work | 実装 | Core / Body | Critical | 2026-09-18 | 2026-09-26 | Blocked |
| 440 | #340 | Work | 実装 | Core / Body | High | 2026-09-26 | 2026-10-01 | Blocked |
| 450 | #341 | Integration | 検証 | Core / Body | Critical | 2026-10-01 | 2026-10-08 | Blocked |
| 460 | #335 | Parent | 設計 | Core / Body | Critical | 2026-09-01 | 2026-10-08 | Blocked |
| 500 | #343 | Work | 実装 | Core / Plugin | Critical | 2026-09-10 | 2026-09-18 | Blocked |
| 510 | #344 | Integration | 検証 | Core / Plugin | Critical | 2026-09-30 | 2026-10-05 | Blocked |
| 520 | #342 | Parent | 設計 | Core / Plugin | Critical | 2026-09-10 | 2026-10-05 | Blocked |
| 530 | #356 | Parent | 設計 | Infrastructure / LLM | High | 2026-08-18 | 2026-09-28 | Blocked |
| 600 | #347 | Work | 実装 | Subsystem / Streaming | High | 2026-10-01 | 2026-10-12 | Blocked |
| 610 | #352 | Work | 実装 | Subsystem / Validation | High | 2026-10-01 | 2026-10-16 | Blocked |
| 620 | #353 | Work | 実装 | Subsystem / Tooling | Medium | 2026-10-05 | 2026-10-18 | Blocked |
| 630 | #346 | Work | 実装 | Subsystem / Avatar | High | 2026-10-08 | 2026-10-15 | Blocked |
| 640 | #351 | Work | 実装 | Subsystem / GUI | High | 2026-10-08 | 2026-10-18 | Blocked |
| 650 | #345 | Parent | 設計 | System Integration | High | 2026-09-30 | 2026-10-20 | Blocked |
| 700 | #360 | Integration | 検証 | System Integration | Critical | 2026-10-20 | 2026-10-31 | Blocked |

---

# 6. Concurrency / LLM Project policy

Project上でも以下をArchitecture invariantとして扱う。

- LLM Role数は固定しない
- Single Executive Authority
- `Role数 != API call数`
- slow LLMで無関係laneをblockしない
- foreground user interaction > low-priority background cognition
- request/resultはrevision / cancel / stale policyを持つ
- Speech playback中next generation可
- Body realtimeはLLM待ちで停止しない
- Game frame loopはExecutive LLM待ちにしない

独立責務は別Issueへ分けるが、Issue分割数をRuntimeの直列call数へ変換しない。

---

# 7. Project sync execution rule

実Project更新前:

1. Project #6をGitHub liveから再取得
2. field ID / option IDを取得
3. V2 Area option不足を確認
4. Issue item重複を確認
5. GitHub正式Parent/Sub-issues current stateを確認
6. #361〜#364を含む新Issue存在確認
7. 本Manifestとの差分をdry-run
8. canonicalと一致した場合のみmutation
9. mutation後Projectを再取得して完全性監査

旧2026-08-07 Snapshotはfield理解の補助に限定し、ID/current stateはlive GitHubを優先する。

---

# 8. Completion

- [x] V2 logical hierarchy再設計
- [x] #361〜#364作成
- [x] Start/Targetを新規Issue本文へ設定
- [x] Design Gate中Status policy確定
- [x] Project priority mapping確定
- [x] V2 Area案更新
- [x] 工程案更新
- [x] 4 LLM固定をManifestから撤回
- [ ] GitHub live Project field IDs取得
- [ ] V2 Area options更新
- [ ] V2全IssueをProject #6へ一意登録
- [ ] Status / Type / Area / Priority / 工程 / Start / Target同期
- [ ] GitHub正式Parent/Sub-issues同期
- [ ] 再取得監査PASS
