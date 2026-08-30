# V2 Production Sequence Authority

Owner: #445
Root: #317
Current Project: GitHub Project #7 `プロジェクトゆらv2`
Historical source: `project_sync_manifest.md` 2026-08-13 synchronized manifest
Status: Current manufacturing-order authority / D10 reconciliation

## 1. 目的

V2の**製造順**と、過去のProject番号・Status・Start/Target dateを分離する。

`project_sync_manifest.md`は2026-08-13時点のProject #6同期履歴として保持する。そこに記録された`工程`は元製造順の証拠だが、Project番号、Status、Start date、Target dateは現在値ではない。

D10以降:

- 現在のProject管理先はProject #7。
- 製造順は本書の`工程` + current dependency graphをAuthorityとする。
- Start date / Target dateは製造順・依存関係・current state監査後にProject #7へ再計画する。
- Issue本文やhistorical manifestの日付から製造順を逆算しない。
- Project #6を更新しない。

## 2. Original sequence

元工程を以下へexactly preserveする。

| 工程 | Issue | Role |
|---:|---:|---|
| 0 | #317 | V2 Root |
| 10 | #318 | Migration Matrix |
| 20 | #319 | Project Sync historical gate |
| 100 | #321 | Foundation Typed Contracts |
| 110 | #322 | Runtime Kernel / Concurrency |
| 120 | #323 | Variable LLM Role / Invocation Contracts |
| 130 | #320 | Core Foundation Parent |
| 140 | #354 | Character Bible |
| 150 | #355 | Character Projection |
| 160 | #324 | Character Parent |
| 170 | #357 | LLM Provider |
| 200 | #349 | Input Gateway |
| 210 | #326 | Input Meaning |
| 220 | #327 | Appraisal / Internal State |
| 230 | #328 | Executive Deliberation |
| 235 | #366 | Goal / Commitment State |
| 240 | #361 | Goal / Activity Planning |
| 250 | #329 | Activity Execution |
| 260 | #362 | Speech Semantics |
| 270 | #330 | Character Language |
| 280 | #363 | Semantic Verification |
| 290 | #331 | Speech Performance |
| 300 | #348 | Speech Runtime / Presentation |
| 310 | #332 | Memory Store / Retrieval |
| 320 | #364 | Reflection / Consolidation |
| 330 | #333 | Attention / Autonomy / Turn |
| 340 | #350 | Core Lifecycle / Graceful Degradation |
| 350 | #358 | TTS Provider |
| 360 | #359 | Persistence Provider |
| 370 | #334 | Brain Integration |
| 380 | #325 | Brain Parent |
| 400 | #336 | Canonical Body Model |
| 410 | #337 | Body Expression |
| 420 | #338 | Body Motion Planner |
| 430 | #339 | Solver / Controller |
| 440 | #340 | Realtime Layers |
| 450 | #341 | Body Integration |
| 460 | #335 | Body Parent |
| 500 | #343 | Plugin Registry / Manifest / Lifecycle |
| 510 | #344 | Plugin Integration |
| 520 | #342 | Plugin Parent |
| 530 | #356 | Infrastructure Parent |
| 600 | #347 | Streaming |
| 610 | #352 | Validation / Concurrency Labs |
| 620 | #353 | Development Tooling |
| 630 | #346 | Avatar |
| 640 | #351 | GUI / Admin |
| 645 | #365 | Game Skill |
| 650 | #345 | Subsystems Parent |
| 700 | #360 | System Integration |

## 3. Later mandatory work insertion rule

元工程作成後に追加されたIssueや必須責務は、番号が大きい/新しいという理由で工程末尾へ送らない。

D10/全Issue監査で各later workを次のいずれかに分類する。

### 3.1 Owner amendment

既存Issueの未完了責務・bugfix・freshness補修・詳細契約で、独立した製造成果物として完成条件を持たないもの。

- owner Issueの工程に吸収する。
- owner Issueのcompletion判定に含める。
- ownerより後の独立工程を作らない。

例候補: #413/#414/#415等のowner contract amendment。最終分類は全Issue監査でfresh確認する。

### 3.2 Independent mandatory work

独立したproduction責務、provider、subsystem、verification gate等で、独自の完了条件を持つもの。

- direct dependencyを確定する。
- predecessorより後、最初のconsumer/integrationより前に新しい工程番号を挿入する。
- 既存工程番号は不要にrenumberしない。整数の空き/小数相当の明示番号を使用できるが、Project field schemaに合わせて最終値を決める。
- downstream Parent/Integration/System completion pathへ必ず接続する。

### 3.3 Historical / management-only

診断lineage、チェックポイント、整理用Issue等でproduction responsibilityを持たないもの。

- production工程へ混入させない。
- ただし全Issue監査ではstate/reasonを正しく整合する。

## 4. Parent / Integration rule

- Parentは子Work/Integrationの完成管理であり、Parent自身へ重複production implementationを作らない。
- Integrationはdirect dependencyの必要Unit/Adjacent Gate完了後に実施する。
- Parentの工程番号は「production codeを書く順番」ではなく、その範囲を完了判定できる最早位置を示す管理位置。
- 未完了upstreamがあるIntegrationをDoneにしない。

## 5. Post-D10 mandatory order

```text
D10 Design Reconciliation PASS
→ ALL V2 Issue state audit (Open + Closed)
→ later work classification / current dependency graph
→ current工程を確定
→ Project #7 Start date / Target date刷新
→ earliest incomplete production WorkをResume Gate
→ production再開
```

この順序を変更しない。D10中にProject日程を先に確定しない。

## 6. Historical manifest handling

`project_sync_manifest.md`は削除・改変して履歴を失わせない。

D10以降に同文書を参照するときは:

- `工程`のhistorical sourceとしてのみ使用する。
- `Project: ktan514 / 6`、旧Status、旧Start/Targetをcurrent Authorityとして使用しない。
- current Project field ID / item ID / option IDはProject #7 liveから取得する。

## 7. Completion

本書がcurrent sequence Authorityになった時点でも、later mandatory workの最終挿入位置は未確定である。

最終current工程はD10 PASS後の全Issue状態監査・依存関係再評価で確定し、その後Project #7へ同期する。
