# 「プロジェクトゆらv2」#7 Sync Runbook

Status: Canonical
Effective: 2026-08-13
Management Issue: #367
Project: `ktan514 / 7`
Repository: `ktan514/ai-liver-yura`
Management spec: `docs/architecture/v2/project_v2_management_spec.md`

## 1. 原則

Project #7のlive設定を、旧Project #6から推測して作らない。

必ず次の順で行う。

1. Auth Permission Gate
2. Read-only Audit / Dry-run
3. Human UI verification（APIで確認不能なWorkflow等）
4. Canonical resolution
5. Mutation
6. Full re-audit

`gh` command実行前には`ktan514`へ認証確認の許可を求める。

## 2. Fixed identity

期待値:

- Owner: `ktan514`
- Project number: `7`
- URL: `https://github.com/users/ktan514/projects/7`
- Repository: `ktan514/ai-liver-yura`
- Visibility: Private

Project ID / field ID / option ID / item IDは毎run live取得し、過去runの値をhard-codeしない。

## 3. Membership invariant

Project #7 membershipはrepository label `v2`と一致させる。

- `v2`あり → Project #7管理対象
- `v2`なし → Project #7管理対象外

V2 Issue / V2 PRにはそれぞれ個別に`v2` labelを付ける。

Project #7に`v2`なしitemが存在する場合は、Project itemだけをmembershipから削除する。

禁止:

- Issue / PR本体のclose/delete
- labelなしitemのarchiveで代替
- Assignee / Milestone / bodyをmembership cleanup理由だけで変更
- 名前やbranch名だけでV2対象へ昇格

## 4. Current V2 scope

V2として明示再計画済みの既存50 Issue:

`#317 #318 #319 #320 #321 #322 #323 #324 #325 #326 #327 #328 #329 #330 #331 #332 #333 #334 #335 #336 #337 #338 #339 #340 #341 #342 #343 #344 #345 #346 #347 #348 #349 #350 #351 #352 #353 #354 #355 #356 #357 #358 #359 #360 #361 #362 #363 #364 #365 #366`

加えてProject #7切替Management Issue #367。

expected V2 Issue scope = **51 Issues**。

confirmed V2 PRは現時点0件。将来V2 PRを作成したらPRへも`v2` labelを個別付与する。

## 5. Auth Permission Gate

Codex / local環境で`gh`を使う前に、最初にユーザーへ次を確認する。

> GitHub CLIの認証状態を確認するため `gh auth status` を実行してよいですか？

許可前に`gh` commandを実行しない。

許可後:

- `gh auth status`
- account = `ch4t9pt`を確認
- account switch / logout禁止
- scope / permission不足ならSTOP

## 6. Phase A audit result — 2026-08-13

確認済み:

- Project identity: PASS
- Project ID: `PVT_kwHOBdOPDs4BgKgD`（audit時点。mutation時は再取得）
- viewerCanUpdate: true
- total Project items: 118
- expected V2 Issue items: 51
- `v2`なしscope外items: 67
- duplicate: 0
- archived: 0
- V2 PR: 0
- formal existing hierarchy: 49/49一致
- #367 parentのみ未設定
- `v2` label: 13/51 present, 38 missing
- Auto-add workflow: enabledは確認、filter / repositoryはAPIでUNVERIFIED

67 scope外itemsはProject #7 membership invariantに違反するため削除対象。

## 7. Human UI Workflow Gate

67件を削除する前に、Project #7 UIでAuto-add workflowを人間確認する。

確認項目:

- workflow = Auto-add to project
- enabled
- repository = `ktan514/ai-liver-yura`
- filter = `label:v2`

filterが`label:v2`でない場合、membership cleanupを実行しない。先にUI設定を修正し、その事実をユーザーが明示する。

APIで確認不能なため、ユーザーのUI確認結果をCheckpointへ記録する。

## 8. Project fields

期待schema:

### Status

- Backlog
- Ready
- In progress
- Review
- Verification
- Blocked
- Done

### 担当ロール

- AI作業
- 人間確認
- 共同判断

### Priority

- P0
- P1
- P2

### Issue level

- Parent
- Work
- Integration
- Management

### Area

Issue本文の`Area:` exact valueを使う。

Management special cases:

- #317 = `Management`
- #318 = `Management`
- #319 = `Management`
- #367 = `Management`

Projectに`Management` optionがなければexisting Area fieldへ非破壊追加する。

### Schedule / estimate

- Start date / Target date: Issue本文の明示値
- Iteration: canonicalなし → 空欄維持
- Size: canonicalなし → 空欄維持
- Estimate: canonicalなし → 空欄維持

## 9. Initial desired Status / role during #367

- #317: `In progress` / `AI作業`
- #318: `Blocked` / `AI作業`
- #319: `Done` / `AI作業`
- #367: `In progress` / `AI作業`
- その他Product Parent / Work / Integration: `Blocked` / `AI作業`

V2 architectureはユーザー承認済みだが、#367 management migrationが完了するまでproduct implementation lineageは開始しない。

## 10. Canonical metadata resolution

Priority:

- #317 = `P0`
- #318/#319/#367 = bodyの`P0`
- その他 = Issue本文のP0/P1/P2

Issue level:

- #317/#318/#319/#367 = `Management`
- その他 = Issue本文

Area:

- #317/#318/#319/#367 = `Management`
- その他 = Issue本文

Start / Target:

- 全51 IssueでIssue本文に明示値あり

Iteration / Size / Estimateは設定しない。

## 11. Mutation order

Human UI Workflow Gate PASS後のみ以下を実施する。

### A. live preflight

- remote canonical再取得
- Project / field / option / item IDs再取得
- 51 scope / 67 scope外を再分類
- duplicate再確認
- V2 PR再検索
- formal hierarchy再確認

### B. `v2` label sync

51 V2 Issueについて:

- already present → no-op
- missing → `v2`追加

scope外Issue/PRへ`v2` labelを付けない。

### C. Project membership cleanup

Project #7 itemのうち、Repository Issue/PRで`v2` labelがないものをProjectから削除する。

- expected audit baseline: 67 items
- mutation時live結果を正本にする
- Issue / PR本体は変更しない
- archiveしない

cleanup後、Project itemsがV2 labeled scopeと一致することを確認する。

### D. Area bootstrap

`Management` optionが不足していればnon-destructiveに追加。

- existing field delete/recreate禁止
- existing options delete/rename禁止
- existing option identity維持

### E. 51 Issue field sync

- Status
- 担当ロール
- Priority
- Issue level
- Area
- Start date
- Target date

Iteration / Size / Estimateは空欄維持。

### F. Formal parent

#367 parentを#317へ追加。

既存49 linksは変更しない。

## 12. Re-audit

mutation後、Project / Issuesを完全再取得する。

必須PASS:

- Project identity一致
- Project membership = `v2` labeled Issue/PRのみ
- scope外 `v2`なし item = 0
- 51 V2 Issues present exactly once
- confirmed V2 PR present exactly once
- duplicate = 0
- 51 Issue `v2` label PASS
- Status PASS
- 担当ロール PASS
- Priority PASS
- Issue level PASS
- Area PASS
- Start / Target PASS
- Iteration / Size / Estimate unchanged/unset
- formal hierarchy = existing49 + #367→#317
- Assignee / Milestone unintended change = 0
- Issue / PR state unintended change = 0
- code / branch / merge mutation = 0

## 13. STOP conditions

- wrong Project identity
- wrong account / missing permission
- duplicate Project item
- duplicate same-name field
- field type conflict
- Auto-add UI verification未完了
- Auto-add filterが`label:v2`でない
- V2 scope ambiguity
- Area / Priority / level / dates contradiction
- unexpected active V2 implementation lineage
- conflicting formal parent
- scope外itemのIssue/PR本体を変更しないと進められない
- canonicalとGitHub live矛盾

## 14. #367 completion

#367をDoneにできる条件:

- Auto-add UI verification PASS
- 51 V2 Issue label PASS
- V2 PR label PASS
- Project membership invariant PASS
- field schema / values PASS
- formal hierarchy PASS
- full re-audit PASS

#367完了後:

- #367 → Done
- #318 → dependency再監査後Ready / In progress
- #321 → dependency再監査後Ready

Project #7 sync完了前にV2 product implementation lineageを開始しない。
