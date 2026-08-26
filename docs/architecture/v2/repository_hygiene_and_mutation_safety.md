# V2リポジトリ衛生・変更安全性契約

状態: #384の正本補足
発効日: 2026-08-21
所有Issue: #384
関連Issue: #207

## 1. 目的

この契約は、AI・人間・自動化がGitHub/Gitへ変更を加える際に、次の事故を構造的に防止する。

- 意図しないbranch作成
- default branchへの誤commit
- tree差分0のno-op commit
- CIを起動するためだけのempty/placeholder commit
- 一時fileのadd→delete履歴汚染
- merge/close後のbranch ref放置
- Target超過・base driftしたOpen PRの放置
- validation-only / CI-only branchの恒久残存
- tool capability確認のためのmutation

注意喚起だけに依存しない。可能なものはdeterministic gateでfail-closedにする。

## 2. 正本

優先順位:

1. GitHub live Issue / PR / branch / exact SHA
2. Issueが指すcanonical design
3. `branch_lifecycle_and_commit_hygiene.md`
4. 本契約
5. `AGENTS.md`
6. chat / memory / summary

矛盾があればGitHub liveとcanonicalを優先し、mutationを開始しない。

## 3. MutationとDiscoveryを分離する

read/search/fetch/list/compareはDiscoveryである。

create/update/delete/merge/ref move/file writeはMutationである。

**Mutation APIを、機能確認・schema確認・接続確認・試行目的で呼んではならない。**

利用可能なMutation toolを確認する場合は、tool schemaやread-only metadataを確認する。実repositoryへdummy branch/file/commitを作って試さない。

## 4. 書込みゲート

すべてのGitHub/Git mutationの直前に、最低限次を確定する。

- Repository
- Work Issue
- PRまたはmutation対象
- target branch
- expected current HEAD
- file/ref/path
- operation
- expected real delta / expected result

1つでも不明ならSTOPする。

複数mutationを行う場合、対象branch/path/expected HEADが変わるたびにGateを更新する。

## 5. Branch指定とprotected trunk

content writeでbranch/refを省略してはならない。

次への直接content writeを禁止する。

- `main`
- `develop`
- `rebuild/v2-foundation`
- 将来追加されるstable/trunk branch

変更はIssueに紐づく作業branchからPRで行う。

GitHub APIがbranch省略時にdefault branchへfallbackする仕様を安全機構として利用しない。省略は入力不備として扱う。

## 6. ブランチ作成ゲート

branch作成前に次を確定する。

- linked Work/Management Issue
- branch purpose
- exact base SHA
- branch lifecycle classification
- 予定するPR base
- 既存active lineageとの重複なし

探索・比較・一時退避だけを目的にshared remote branchを作成しない。

branchを作成した後、予定したreal deltaを入れずに終了する場合は、そのrefを残さない。

`tmp/*`、`*DO_NOT_USE*`など「使わないこと」を名前で表現するshared branchを履歴保管目的で維持しない。必要な証拠はIssue/PR/commit SHAへ記録する。

## 7. 無変更・仮置きゲート

commit/write前にcurrent content/blob/treeとintended contentを比較する。

real deltaが0ならcommitしない。

禁止例:

- empty commitでworkflowを起動する
- `NOOP`
- `nonexistent`
- `.trigger`
- `.issue_sync_marker`
- `tmp-never-used`
- `tmp.txt`
- temporary `ISSUE_PLAN.md`
- 空白だけ、無意味なcommentだけ、仮文字だけの変更
- 直後に消す前提のmarker file

CI再実行にはworkflow rerun、PR reopen、workflow_dispatch等の正規mechanismを使う。履歴を動かすためにrepository contentを変更しない。

## 8. コミット前後の確認

### commit前

- current branchを確認
- protected trunkではないことを確認
- linked Issue/PRを確認
- staged pathsを確認
- expected path allowlist外がないことを確認
- placeholder pathがないことを確認
- staged diffが空でないことを確認

### commit後・push前

- commit message
- parent SHA
- changed paths
- stats
- accidental/generated file
- tree差分が実在すること

を再確認する。

### push後

GitHub live branch headを再取得し、local/remote/PR headがexpected SHAへ一致することを確認する。

## 9. PR・ブランチのライフサイクル

非trunk branchは必ず次のどれかである。

- ACTIVE
- BLOCKED / PAUSED
- MERGED
- ABANDONED
- TEST_ONLY

### ACTIVE

- linked Issue
- Open PR
- current exact head
- Resume Checkpoint
- current baseとのrelation
を持つ。

### BLOCKED / PAUSED

- blocker/reason
- exact head
- behind/ahead
- next resume gate
をIssueへ記録する。

### 日程の正本

日程の唯一の正本はGitHub Projectの`Start date`および`Target date`フィールドである。

- Issue本文に記載された日付は日程の正本として使用しない。
- 本文とProjectフィールドが不一致の場合は、必ずProjectフィールドを優先する。
- Issue本文を根拠にProjectフィールドを更新しない。
- 必要時は本文の日付をProjectフィールドへ同期するか、本文の重複記載を削除する。
- 日程は予定情報であり、着手、完了、Resume Gate、STOPの条件ではない。
- 日程の変更はGitHub Projectフィールドで行う。

### MERGED

PR mergeだけではlifecycle完了ではない。

- merge resultを記録
- branch ref削除
までを完了とする。

### ABANDONED

- close unmerged
- superseded/abandoned reasonを記録
- branch ref削除

### TEST_ONLY

- evidenceをIssue/PRへ記録
- PR close unmerged
- branch ref削除

再利用可能なCI utilityだけは、owner Issueと再利用理由を明示した場合に限り例外的に保持できる。

## 10. 古いOpen PRのゲート

定期監査で最低限次を確認する。

- base branchからのbehind count
- 最終checkpointの古さ
- active owner Issueの存在
- superseding PR/branchの存在
- mergeability

次の場合は自動的にmerge/closeせず、人間/owner Issueへreconciliationを要求する。

- behindが大きいが固有成果がある
- canonicalが更新されている
- active lineageの重複が疑われる

固有成果がcurrent owner branchへ完全吸収済みの場合は、古いPRをsupersededとしてclose-unmergedしbranch refを削除する。

## 11. 固有コミットのないブランチ

Git branchは必ずcommitを指すため「0 commit branch」は、基準branchに対してunique commitが0件という意味で扱う。

`base...branch`でahead=0のbranchにactive owner/特殊用途がなければ削除する。

branchが単に古いbase commitを指しており、現在baseよりbehindだけの状態も同様である。

## 12. 事故対応

誤mutationを検知したら:

1. 追加mutationを停止する
2. live head / parent / changed pathを取得する
3. Issue #384またはowner Issueへ事故を記録する
4. current treeへ残る実害を確認する
5. protected/shared historyを無断rewriteしない
6. corrective commit / branch delete / PR closeのうち最小安全手段を選ぶ
7. post-correction live readbackを行う
8. root causeを本契約またはguardへ反映する

事故を隠すためのforce push/rebase/history rewriteを行わない。必要な場合は明示的な人間承認を得る。

## 13. 既知事故からの原因分類

### 変更操作を探索へ流用

create/update APIをcapability確認に使い、dummy branch/fileを作成した。

対策: DiscoveryとMutationをtool levelで分離し、MutationはWrite Gate後だけ許可する。

### 暗黙の対象フォールバック

branchを省略したfile writeがdefault `main`へ到達した。

対策: branch/refを必須入力として扱い、protected trunk direct writeを禁止する。

### 無変更書込み

current contentと同一内容をupdateし、tree差分0 commitを作成した。

対策: pre-write blob/content equality gate。

### CI起動のための履歴変更

workflow起動目的のplaceholder/temporary commitを作った。

対策: rerun/reopen/dispatchを使用し、content mutationを禁止する。

### ライフサイクル後始末の欠落

PR close/merge後にbranch refが残った。

対策: close/mergeとref deleteを1つのlifecycle完了条件として扱う。

### 古いOpen PR監査の欠落

Target超過・base driftがあるPRがOpen Draftのまま残った。

対策: 定期stale audit + explicit BLOCKED/PAUSED/Replan分類。

## 14. 決定論的なコミット衛生ガード

#384完了には、文書ルールだけでなくdeterministic guardを追加する。

最低限PR rangeを検査する。

1. empty/tree-identical commit
2. placeholder pathの追加
3. placeholder add→delete pair
4. workflow triggerだけを目的とするhistory-only mutation
5. forbidden direct-trunk workflow/automation patternの検査可能範囲

Guardは外部LLM/APIを必要としない。

既知名称だけのallow/deny listに依存して未知事故を見逃さないよう、次を組み合わせる。

- tree equality
- changed path
- file lifecycle
- commit parent/tree relation
- bounded explicit placeholder deny-list

## 15. リポジトリ保護

GitHub側でも事故を止めるため、権限が許す場合は少なくとも次をRuleset/branch protection対象とする。

- `main`
- `develop`
- `rebuild/v2-foundation`

目的:

- direct push抑止
- PR経由変更
- force push禁止
- delete禁止
- 必要なstatus checkの要求

現在のAPI監査で少なくとも`main`と`develop`は`protected=false`だったため、repository-side protectionは別途設定確認・導入対象とする。

## 16. AI・Codexへの周知

Repository rootの`AGENTS.md`を全AI共通の最短実行規則とする。

ChatGPT、local Codex、GitHub Codex、Gemini、将来のAIは、本契約を読んでいないことを理由に例外扱いしない。

Codexへ実装を依頼するPromptにも、Issue/branch/base/headだけでなくWrite Gate・no-op禁止・branch lifecycleを明記する。
