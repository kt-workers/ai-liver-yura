# AI Liver ゆら V2 GitHub Projects Sync Manifest

Status: Draft / #319
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

V2 Issue hierarchyをGitHub Projects v2「プロジェクトゆら」へ同期するための正本。

Project field / formal Sub-issue操作前にGitHub liveからfield ID / option ID / item IDを再取得し、旧Snapshot IDを推測利用しない。

実行手順・STOP条件は`project_sync_runbook.md`を正本とする。

---

## 2. Design Gate Status Policy

- #317: In progress
- #318: In progress（Migration再同期完了、Design Gate確認待ち）
- #319: Blocked（Manifest/Runbook完成、Project/Sub-issue実mutation可能環境待ち）
- Product/Design Work・Parent・Integration: 原則Blocked by #317 Design Gate

ユーザーがV2 canonical designを明示確認するまで製品コードIssueをIn progressへしない。

---

## 3. 推奨Area

- Management
- Core / Foundation
- Core / Character Definition
- Core / Brain / Input
- Core / Brain / Appraisal
- Core / Brain / Executive
- Core / Brain / Goal State
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
- Subsystem / Game Skill
- Subsystem / GUI
- Subsystem / Validation
- Subsystem / Tooling
- System Integration

---

## 4. Parent / Sub-issue hierarchy

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
│  ├─ #366 Goal / Commitment State [Work]
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
├─ #356 Infrastructure [Parent]
│  ├─ #357 LLM Provider [Work]
│  ├─ #358 TTS Provider [Work]
│  └─ #359 Persistence Provider [Work]
├─ #345 Subsystems [Parent]
│  ├─ #346 Avatar [Work]
│  ├─ #347 Streaming [Work]
│  ├─ #365 Game Skill [Work]
│  ├─ #351 GUI / Admin [Work]
│  ├─ #352 Validation / Concurrency Labs [Work]
│  └─ #353 Development Tooling [Work]
└─ #360 System Integration [Integration]
```

---

## 5. Project Items / Schedule

| 工程 | Issue | Level | Area | Priority | Start | Target | Gate Status |
|---:|---:|---|---|---|---|---|---|
| 0 | #317 | Management/Root | Management | Critical | 2026-08-12 | 2026-10-31 | In progress |
| 10 | #318 | Management | Management | Critical | 2026-08-12 | 2026-08-16 | In progress |
| 20 | #319 | Management | Management | Critical | 2026-08-12 | 2026-08-17 | Blocked |
| 100 | #321 | Work | Core/Foundation | Critical | 2026-08-13 | 2026-08-15 | Blocked |
| 110 | #322 | Work | Core/Foundation | Critical | 2026-08-15 | 2026-08-21 | Blocked |
| 120 | #323 | Work | Core/Foundation | Critical | 2026-08-15 | 2026-08-20 | Blocked |
| 130 | #320 | Parent | Core/Foundation | Critical | 2026-08-13 | 2026-08-26 | Blocked |
| 140 | #354 | Work | Core/Character | Critical | 2026-08-17 | 2026-08-21 | Blocked |
| 150 | #355 | Work | Core/Character | Critical | 2026-08-21 | 2026-08-24 | Blocked |
| 160 | #324 | Parent | Core/Character | Critical | 2026-08-17 | 2026-08-24 | Blocked |
| 170 | #357 | Work | Infrastructure/LLM | Critical | 2026-08-18 | 2026-08-27 | Blocked |
| 200 | #349 | Work | Brain/Input | Critical | 2026-08-19 | 2026-08-23 | Blocked |
| 210 | #326 | Work | Brain/Input | Critical | 2026-08-19 | 2026-08-24 | Blocked |
| 220 | #327 | Work | Brain/Appraisal | Critical | 2026-08-24 | 2026-08-31 | Blocked |
| 230 | #328 | Work | Brain/Executive | Critical | 2026-08-31 | 2026-09-06 | Blocked |
| 235 | #366 | Work | Brain/Goal State | Critical | 2026-09-04 | 2026-09-09 | Blocked |
| 240 | #361 | Work | Brain/Goal Planning | Critical | 2026-09-06 | 2026-09-11 | Blocked |
| 250 | #329 | Work | Brain/Activity | Critical | 2026-09-05 | 2026-09-10 | Blocked |
| 260 | #362 | Work | Brain/Speech Semantics | Critical | 2026-09-06 | 2026-09-11 | Blocked |
| 270 | #330 | Work | Brain/Character Language | Critical | 2026-09-10 | 2026-09-15 | Blocked |
| 280 | #363 | Work | Brain/Semantic Verification | Critical | 2026-09-12 | 2026-09-17 | Blocked |
| 290 | #331 | Work | Brain/Speech Runtime | High | 2026-09-14 | 2026-09-17 | Blocked |
| 300 | #348 | Work | Brain/Speech Runtime | Critical | 2026-09-17 | 2026-09-23 | Blocked |
| 310 | #332 | Work | Brain/Memory | High | 2026-09-15 | 2026-09-22 | Blocked |
| 320 | #364 | Work | Brain/Reflection | High | 2026-09-18 | 2026-09-24 | Blocked |
| 330 | #333 | Work | Brain/Autonomy | High | 2026-09-20 | 2026-09-25 | Blocked |
| 340 | #350 | Work | Core/Foundation | Critical | 2026-09-18 | 2026-09-25 | Blocked |
| 350 | #358 | Work | Infrastructure/TTS | High | 2026-09-22 | 2026-09-27 | Blocked |
| 360 | #359 | Work | Infrastructure/Persistence | High | 2026-09-22 | 2026-09-28 | Blocked |
| 370 | #334 | Integration | Brain Integration | Critical | 2026-09-25 | 2026-10-02 | Blocked |
| 380 | #325 | Parent | Brain | Critical | 2026-08-19 | 2026-10-05 | Blocked |
| 400 | #336 | Work | Body | Critical | 2026-09-01 | 2026-09-07 | Blocked |
| 410 | #337 | Work | Body | Critical | 2026-09-07 | 2026-09-12 | Blocked |
| 420 | #338 | Work | Body | Critical | 2026-09-12 | 2026-09-19 | Blocked |
| 430 | #339 | Work | Body | Critical | 2026-09-18 | 2026-09-26 | Blocked |
| 440 | #340 | Work | Body | High | 2026-09-26 | 2026-10-01 | Blocked |
| 450 | #341 | Integration | Body | Critical | 2026-10-01 | 2026-10-08 | Blocked |
| 460 | #335 | Parent | Body | Critical | 2026-09-01 | 2026-10-08 | Blocked |
| 500 | #343 | Work | Plugin | Critical | 2026-09-10 | 2026-09-18 | Blocked |
| 510 | #344 | Integration | Plugin | Critical | 2026-09-30 | 2026-10-05 | Blocked |
| 520 | #342 | Parent | Plugin | Critical | 2026-09-10 | 2026-10-05 | Blocked |
| 530 | #356 | Parent | Infrastructure | High | 2026-08-18 | 2026-09-28 | Blocked |
| 600 | #347 | Work | Subsystem/Streaming | High | 2026-10-01 | 2026-10-12 | Blocked |
| 610 | #352 | Work | Subsystem/Validation | High | 2026-10-01 | 2026-10-16 | Blocked |
| 620 | #353 | Work | Subsystem/Tooling | Medium | 2026-10-05 | 2026-10-18 | Blocked |
| 630 | #346 | Work | Subsystem/Avatar | High | 2026-10-08 | 2026-10-15 | Blocked |
| 640 | #351 | Work | Subsystem/GUI | High | 2026-10-08 | 2026-10-18 | Blocked |
| 645 | #365 | Work | Subsystem/Game Skill | High | 2026-10-08 | 2026-10-20 | Blocked |
| 650 | #345 | Parent | Subsystems | High | 2026-09-30 | 2026-10-20 | Blocked |
| 700 | #360 | Integration | System Integration | Critical | 2026-10-20 | 2026-10-31 | Blocked |

---

## 6. Architecture invariants to preserve in Project

- LLM Role数を固定しない
- Single Executive Authority
- current Goal / Commitment正本は#366
- `Logical Role count != API call count`
- responsibility separationを直列LLM chainへしない
- slow LLM / TTS / DB / Plugin / Subsystemでunrelated laneをblockしない
- foreground interaction > low-priority background cognition
- source_context_revision / goal_revision / cancellation / stale / supersede
- Speech playback中next generation可
- Body realtimeはLLM待ちで停止しない
- Game frame loopはCore Executive LLM latency非依存
- Streaming burstでCore starvationなし
- Pluginをoptional性だけで定義しない

---

## 7. Sync execution rule

1. `project_sync_runbook.md`に従いProject #6をlive取得
2. field IDs / option IDs / current item IDsを取得
3. 新Area optionsを確認/追加
4. item重複を確認
5. #361〜#366を含むIssue existence確認
6. formal Parent/Sub-issue current state確認
7. Manifestとの差分をdry-run
8. canonicalと一致した場合のみmutation
9. mutation後Projectを再取得して完全性監査

現ChatGPT環境ではGitHub ConnectorにProjects v2 / formal Sub-issue mutation actionがなく、containerにも認証済み`gh`がないため、実mutationだけがBlocked。古いIDを推測使用しない。

---

## 8. Completion

- [x] V2 logical hierarchy再設計
- [x] #361〜#366作成
- [x] Start/Targetを新規Issue本文へ設定
- [x] Design Gate status policy確定
- [x] Area案更新
- [x] 工程案更新
- [x] 4 LLM固定撤回を反映
- [x] Game SkillをSubsystem hierarchyへ追加
- [x] Persistent Goal / Commitment StateをBrain hierarchyへ追加
- [x] live-ID/dry-run/mutation/re-audit runbook作成
- [ ] GitHub live Project field IDs取得
- [ ] V2 Area options更新
- [ ] V2全IssueをProject #6へ一意登録
- [ ] Status / Type / Area / Priority / 工程 / Start / Target同期
- [ ] formal Parent/Sub-issues同期
- [ ] 再取得監査PASS
