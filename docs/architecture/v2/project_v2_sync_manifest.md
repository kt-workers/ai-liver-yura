# 「プロジェクトゆらv2」#7 Sync Manifest

Status: Canonical
Effective: 2026-08-13
Project: `ktan514 / 7`
Repository: `ktan514/ai-liver-yura`
Root: #317
Management migration: #367
Management spec: `docs/architecture/v2/project_v2_management_spec.md`
Runbook: `docs/architecture/v2/project_v2_sync_runbook.md`

## 1. Membership canonical

Project #7は`v2` labelがあるIssue / Pull Requestだけを管理する。

- `v2`あり → membership対象
- `v2`なし → membership対象外

`v2`なしの既存Project itemはProject #7 membershipから削除する。
Issue / PR本体のclose/delete/archive/label/Assignee/Milestoneは変更しない。

Auto-add desired filter: `label:v2`。

## 2. Current expected Issue scope

51 Issues:

`#317 #318 #319 #320 #321 #322 #323 #324 #325 #326 #327 #328 #329 #330 #331 #332 #333 #334 #335 #336 #337 #338 #339 #340 #341 #342 #343 #344 #345 #346 #347 #348 #349 #350 #351 #352 #353 #354 #355 #356 #357 #358 #359 #360 #361 #362 #363 #364 #365 #366 #367`

現時点confirmed V2 PR = 0。

## 3. Phase A audit snapshot

Audit timestamp: 2026-08-13T02:26:48+0900

- Project identity: PASS
- Project ID at audit: `PVT_kwHOBdOPDs4BgKgD`
- total items: 118
- expected V2 Issue items: 51
- `v2`なしscope外 items: 67
- duplicates: 0
- archived items: 0
- `v2` label present: 13
- `v2` label missing: 38
- formal existing canonical links: 49/49 PASS
- #367 parent missing
- Auto-add enabled: confirmed
- Auto-add filter/repository: API UNVERIFIED

Project ID / field IDs / option IDs / item IDsはmutation時にlive再取得する。

## 4. Project field schema

### Status

`Backlog`, `Ready`, `In progress`, `Review`, `Verification`, `Blocked`, `Done`

### 担当ロール

`AI作業`, `人間確認`, `共同判断`

### Priority

`P0`, `P1`, `P2`

### Issue level

`Parent`, `Work`, `Integration`, `Management`

### Area

Issue本文の`Area:` exact value。

Management special cases:

- #317 = `Management`
- #318 = `Management`
- #319 = `Management`
- #367 = `Management`

Audit時Project Areaには`Management` optionが不足。non-destructive add対象。

### Schedule / estimate

- Start date = Issue本文の明示値
- Target date = Issue本文の明示値
- Iteration = unset
- Size = unset
- Estimate = unset

## 5. Canonical metadata exceptions

#317:

- Priority = `P0`
- Issue level = `Management`
- Area = `Management`

#318:

- Issue level = `Management`
- Area = `Management`
- Priority = `P0`

#319:

- Issue level = `Management`
- Area = `Management`
- Priority = `P0`

#367:

- Issue level = `Management`
- Area = `Management`
- Priority = `P0`

その他IssueはIssue本文のPriority / Issue level / Areaを正本とする。

## 6. Desired migration Status / role

| Issue scope | Status | 担当ロール |
|---|---|---|
| #317 | In progress | AI作業 |
| #318 | Blocked | AI作業 |
| #319 | Done | AI作業 |
| #367 | In progress | AI作業 |
| その他V2 Parent / Work / Integration | Blocked | AI作業 |

V2 architectureはユーザー承認済み。ただし#367完了まではproduct implementation lineageを開始しない。

## 7. Required mutation

Human UIでAuto-add workflowが次であることを確認した後だけ実施:

- enabled
- repository = `ktan514/ai-liver-yura`
- filter = `label:v2`

Mutation:

1. 51 Issueのmissing `v2` labelを追加
2. `v2` labelなしProject itemsをProject #7 membershipから削除
3. Area `Management` optionを不足時のみ非破壊追加
4. 51 IssuesのStatus / 担当ロール / Priority / Issue level / Area / Start / Targetを同期
5. Iteration / Size / Estimateは未設定維持
6. #367 formal parentを#317へ追加
7. 完全再監査

## 8. Explicit non-mutations

- scope外Issue / PRへ`v2` labelを追加しない
- Issue / PR本体をclose/deleteしない
- scope外Project itemをarchiveで残さない
- Assignees変更なし
- Milestone変更なし
- source code変更なし
- implementation branch / PR作成なし
- V1 lineage変更なし
- old Project #6 mutationなし

## 9. Completion criteria

#367 PASS条件:

- Auto-add UI verification PASS
- Project membership = `v2` labeled Issue/PR only
- unlabeled Project item = 0
- 51 V2 Issue labels = PASS
- V2 PR labels = PASS
- exact-one Project item = PASS
- duplicate = 0
- Status = PASS
- 担当ロール = PASS
- Priority = PASS
- Issue level = PASS
- Area = PASS
- Start / Target = PASS
- Iteration / Size / Estimate unchanged/unset
- formal hierarchy = 50 links including #367→#317
- unintended Issue/PR/repository mutations = 0

## 10. After #367

Project #7がV2 management authorityとなる。

次:

1. #318 old implementation lineage整理のStart Gate
2. #321 Typed Contracts dependency / Resume Gate
3. 1 Work Issue = 1 active implementation lineageでV2 product implementation開始
