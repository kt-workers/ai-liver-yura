# 「プロジェクトゆらv2」#7 Sync Runbook

Status: Canonical
Effective: 2026-08-13
Management Issue: #367
Project: `ktan514 / 7`
Repository: `ktan514/ai-liver-yura`
Management spec: `docs/architecture/v2/project_v2_management_spec.md`

## 1. 原則

Project #7のlive設定を、旧Project #6から推測して作らない。

必ず二段階で行う。

1. Audit / Dry-run
2. Canonical resolution後のMutation / Re-audit

`gh` command実行前には、運用ルールに従って`ktan514`へ認証確認の許可を求める。

## 2. 固定Identity

期待値:

- Owner: `ktan514`
- Project number: `7`
- URL: `https://github.com/users/ktan514/projects/7`
- Repository: `ktan514/ai-liver-yura`
- Visibility: Private

Project IDは固定値として文書へハードコードせず、毎run live取得する。

## 3. Current migration scope

V2として既に明示再計画済みの既存50 Issue:

`#317 #318 #319 #320 #321 #322 #323 #324 #325 #326 #327 #328 #329 #330 #331 #332 #333 #334 #335 #336 #337 #338 #339 #340 #341 #342 #343 #344 #345 #346 #347 #348 #349 #350 #351 #352 #353 #354 #355 #356 #357 #358 #359 #360 #361 #362 #363 #364 #365 #366`

加えてProject #7切替Management Issue #367。

現時点のexpected V2 Issue scope = **51 Issues**。

V2 PRはGitHub live検索で確定する。`v2` labelなしのPRを題名だけでV2と推測しない。ただしV2 implementation lineageとしてIssue / branch / canonicalから一意に確認できたPRがあれば、mutation前に対象として明示し`v2` labelを個別付与する。

## 4. Phase A — Auth Permission Gate

Codex / local環境で`gh`を使う場合、最初にユーザーへ次だけを確認する。

> GitHub CLIの認証状態を確認するため `gh auth status` を実行してよいですか？

明示許可前に`gh auth status`を含む`gh` commandを実行しない。

許可後:

- `gh auth status`
- accountが`ch4t9pt`か確認
- account switch / logout禁止
- required scope不足ならSTOP

## 5. Phase A — Project live audit

Project #7についてlive取得する。

最低限:

- Project ID
- title
- visibility
- viewerCanUpdate
- fields
- single-select options
- current items
- item duplicates
- workflows / Auto-add（API/CLIで取得可能な範囲のみ）

API / CLIでworkflow条件を確認できない場合、`未確認`として報告しPASS扱いしない。

## 6. Phase A — Repository V2 audit

51 Issue全件についてlive取得:

- issue state
- labels
- body metadata
- formal parent
- Start date / Target date
- Priority
- Issue level
- Area

V2 PRを検索:

- existing `label:v2` PR
- V2 branch / linked V2 Issueから明示的にV2と確認できるPR

旧Issue / 旧PRをscopeへ自動追加しない。

## 7. `v2` label rule

51 V2 Issueには`v2` labelが必要。

- already present → no-op
- missing → mutation対象
- unrelated Issueへ追加しない

V2 PRも個別にlabelを付ける。

Issue labelからPRへ自動継承されると考えない。

## 8. Project fields

期待するfield semantics:

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

Issue本文の`Area:`と一致するoptionを使う。

**旧Project #6のbroad Area mappingを使用しない。**

### Optional / schedule fields

- Iteration
- Start date
- Target date
- Size
- Estimate

Iteration / Size / Estimateは根拠がなければ空欄。
Start / TargetはIssue本文 / V2 canonicalの明示値を使う。

## 9. Initial Status / role during #367

Project #7切替作業中:

- #317: `In progress` / `AI作業`
  - canonical architectureはユーザー承認済み
  - #367 management gate中
- #318: `Blocked` / `AI作業`
  - #367完了後にold lineage整理へ進む
- #319: `Done` / `AI作業`
- #367: `In progress` / `AI作業`
- Product Parent / Work / Integration: 原則 `Blocked` / `AI作業` until #367 PASS

#367完了後:

- #367 → Done
- #318 → ReadyまたはIn progress（実際にold lineage整理を開始する時点で決定）
- 最初の実装Work #321 → dependency再監査後Ready

他Issueを日程だけで自動Ready/In progressへしない。

## 10. Field creation / option bootstrap

不足field / optionがある場合:

- existing fieldを削除・再作成しない
- existing optionを理由なくrename/deleteしない
- IDをlive取得
- desired schemaをmutation前Dry-runへ明示
- option追加可能な場合のみ非破壊追加
- field typeが想定と異なる場合STOP

特にAreaは51 Issueのlive bodyからunique valuesを収集してからdesired option setを確定する。

## 11. Auto-add workflow

Desired:

`label:v2`

ただしworkflow設定をAPI / `gh`で取得・変更できない場合:

- 確認済みと主張しない
- 手動UI操作が必要な項目として報告
- 他のProject同期がPASSでも`Auto-add workflow: UNVERIFIED`を明記

## 12. Project item sync

51 Issue + confirmed V2 PRについて:

- exact one item
- zero → add
- one → reuse
- duplicate → STOP

旧Project #6からitem ID / field ID / option IDを流用しない。

## 13. Formal hierarchy

formal Parent/Sub-issueは既にGitHub Issue側のV2 hierarchyが正本。

Project #7移行のためにhierarchyを作り直さない。

Auditでcurrent formal hierarchyがV2 canonicalと一致することを確認し、不一致ならProject mutationとは分離してSTOP / reconciliationする。

#367は#317配下Managementとしてformal parent設定対象。

## 14. Mutation後re-audit

最低限:

- scope Issue count
- scope PR count
- `v2` label
- exact-one Project item
- field values
- Status
- 担当ロール
- Priority
- Issue level
- Area
- Start / Target
- formal hierarchy
- duplicate 0
- unrelated item mutation 0
- Assignee / Milestone unintended change 0
- code / branch / PR state / merge unintended change 0

## 15. STOP conditions

以下はmutation前または途中でSTOP:

- wrong Project owner / number / ID
- wrong authenticated account
- missing permission
- duplicate item
- duplicate same-name field
- field type conflict
- Area valueをIssue本文から一意に解決不能
- Priority / level / dates contradiction
- formal parent contradiction
- unexpected active V2 implementation lineage
- scope外Issue / PRへのmutationが必要になる
- workflowを確認不能なのに確認済みとして進める必要がある
- canonicalとlive GitHubに矛盾

## 16. #367 completion

#367をDoneにできる条件:

- 51 V2 Issueの`v2` label PASS
- confirmed V2 PR label PASS
- Project #7 exact-one item PASS
- required field schema PASS
- canonical field sync PASS
- hierarchy PASS
- re-audit PASS
- Auto-add workflowは確認済み、またはAPIで確認不能なら人間UI確認待ちとしてVerification / Blockedに残す

Project #7 sync完了前にV2 product implementation lineageを開始しない。
