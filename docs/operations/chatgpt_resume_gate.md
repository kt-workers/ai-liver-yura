# ChatGPT 作業再開 Resume Gate

## 1. 目的

ChatGPT / Codex / 人間がチャットをまたいで作業するとき、古い要約・記憶・Issue番号の取り違え・重複実装によって誤った作業を再開しないための運用契約を定義する。

本ルールは製品設計ではなく、プロジェクト運用の安全Gateである。

関連:

- Project運用ハブ: Issue #207
- 根本原因対策: Issue #314

## 2. 開発開始禁止条件

新しいチャットでユーザーが「続き」「再開」「前のチャットを引き継ぐ」等を依頼した場合、以下の Resume Gate が PASS するまで、次の操作をしてはならない。

- 製品コード変更
- branch作成
- implementation PR作成
- 既存implementation branchへのpush
- merge
- 新しい実装Issueの作成

状態監査、Issue/PR整理、設計・運用ドキュメント確認、reconciliationは許可する。

## 3. 情報源のAuthority

### 3.1 現在状態の事実

優先順位は次の通り。

1. GitHub live Issue / PR / branch / commit SHA
2. 対象Issueの最新 Resume Checkpoint
3. GitHub Projects v2 live fields。直接取得できない場合は最新同期snapshot。ただしsnapshot日時を必ず確認する
4. 直前ChatGPTチャットの会話内容
5. ChatGPT Project conversation summary / personal memory /自動要約

5は候補発見にのみ利用する。Issue番号、PR番号、branch、進捗、完了判定、次作業の確定に使用してはならない。

GitHub liveとsummary/memoryが矛盾した場合、GitHub liveを採用し、Resume Gateは一旦 STOP として差異をreconciliationする。

### 3.2 設計意図

優先順位は次の通り。

1. 対象Issueが正本として指すcanonical design / ADR
2. 親Issue / architecture docs
3. 対象Issueの最新decision comment
4. 直前ChatGPTチャット
5. summary / memory

新しい設計が旧設計をsupersedeしている場合、古い文書の存在だけを理由に旧方針へ戻さない。

## 4. Resume Gate手順

### Step 1: 候補抽出

直前チャット情報から次を候補として抽出する。

- Issue
- PR
- branch
- canonical design
- 最後に行っていた作業

この段階では確定しない。

### Step 2: 運用ハブ確認

Issue #207の最新運用ルールを読む。

Projects v2 snapshotを使う場合、snapshot日時を確認し、対象作業より古い場合はlive stateの代替として扱わない。

### Step 3: Canonical design確認

対象Issue本文が正本として指している設計書・ADR・設計PRを読む。

正本が複数ある、またはsupersede関係が不明な場合はSTOPする。

### Step 4: GitHub live照合

最低限次をlive取得する。

- Issue number + title + state
- 関連PR number + title + state + draft/merged
- branch name
- base branch
- base SHA
- head SHA
- PR chain
- 最新CI/Verification状態

Issue番号だけで同一性を判断しない。titleと責務も照合する。

### Step 5: Active lineage監査

同じWork Issueについてactive implementation lineageが複数ないか確認する。

分類:

- `canonical`
- `superseded`
- `validation-only`
- `ci-only`
- `abandon`
- `unknown`

`canonical`候補が2本以上、または`unknown`がある場合はSTOPする。

### Step 6: Resume Checkpoint照合

対象Issueの最新 Resume Checkpoint とlive GitHubを比較する。

次が一致していることを確認する。

- Issue
- canonical design
- active lineage
- working branch
- PR
- head SHA
- current phase/status
- last verification
- next action

SHAが進んでいる場合は、その差分が同じlineageの継続として説明可能か確認する。

### Step 7: Resume Certificate提示

開発操作前に、必ずユーザーへ以下を提示する。

```text
Resume Gate: PASS / STOP
対象Issue: #N <title>
設計正本: <path / PR>
active lineage: <PR chain>
作業branch: <branch>
Base: <branch>@<SHA>
Head: <branch>@<SHA>
現在のphase/status: <state>
最終検証: <CI/manual/date>
次のaction: <one concrete action>
conflicts: none / <details>
情報鮮度: <GitHub checked timestamp / snapshot timestamp>
```

これを作れない場合はPASSにしてはならない。

### Step 8: 開発開始

Resume GateがPASSした後にのみ、既存lineageの続きを実行する。

新branch / 新PRが必要になった場合も、作成直前に重複lineage監査を再実行する。

## 5. STOP条件

以下のいずれかがあれば必ずSTOPする。

- memory/summaryとGitHub liveのIssue/PR/branchが一致しない
- Issue番号は一致するがtitle/責務が一致しない
- canonical designが不明
- 同じWork Issueに複数active implementation lineageがある
- latest Resume Checkpointとlive branch/PRが説明不能に不一致
- PR base/headが想定と異なる
- superseded/validation-only/ci-onlyの分類が不明
- Projects snapshotだけが作業中を示し、live Issue/PRと整合しない
- 直前チャットの全文状態を確認できず、GitHub側にもcheckpointがない

STOP時は推測で補完しない。reconciliationのみ行う。

## 6. Resume Checkpoint

GitHubへ投稿するResume CheckpointおよびResume Certificateの人間向け説明は
日本語で書く。status値、branch名、command、file path、SHA、API/class/function/
field名、machine-readable JSON、外部API原文の必要な引用だけは英語のままでよい。
既存投稿の翻訳は要求しない。

対象Work Issueへ、重要な状態遷移のたびに次の形式でコメントする。

```text
## Resume Checkpoint YYYY-MM-DD HH:mm JST

Issue: #N <title>
Canonical design: <path / PR>
Active lineage: <PR chain>
Working branch: <branch>
Base: <branch>@<SHA>
Head: <branch>@<SHA>
Completed:
- ...

Current status:
- ...

Last verified:
- ...

Blocked / conflicts:
- none / ...

Next action:
1. ...

Do not resume from:
- <superseded/abandoned/validation-only branches or PRs>
```

### Checkpointを残すタイミング

- 設計方針確定/変更
- branch作成
- Draft PR作成
- CI結果確定
- Verificationへ移動
- blocker発生
- active lineageのsupersede/close
- ユーザーがチャット切替を明示
- 長時間作業中に大きな工程が完了

チャット終了時だけに依存しない。

## 7. 1 Work Issue = 1 Active Implementation Lineage

Work Issueごとにactive implementation lineageは原則1本とする。

stacked PRは1本のlineageとして扱えるが、IssueのResume Checkpointに順序を明記する。

例:

```text
canonical lineage:
PR #A -> PR #B -> PR #C
```

CI-only / validation-only PRはimplementation lineageではない。ただしPR title/bodyで用途を明示し、検証後は原則closeする。

複数lineageを発見した場合、どちらかを勝手に継続しない。`canonical / superseded / validation-only / abandon`を確定してから再開する。

## 8. 新規Issue / Branch / PR作成前のSemantic Duplicate Gate

Issue #207の意味的重複確認ルールをhard gateとして扱う。

最低限比較する。

1. ユーザー可視の症状・要望
2. 守るべき設計原則 / invariant
3. パイプライン上の責務所有者
4. 受入条件
5. existing Issue/PR state
6. 後続設計でsupersedeされていないか

changed filesが違うだけでは独立作業の根拠にならない。

## 9. ChatGPT Project設定用の必須ルール

Project Instructionsには少なくとも次の意味を持つルールを置く。

> 新規チャットで既存作業の続き・再開・引き継ぎを依頼された場合、要約・memoryだけから作業対象を推測してはならない。製品コード変更、branch作成、implementation PR作成より前に、直前チャットから候補を抽出し、Issue #207、対象Issueが指すcanonical design、GitHub liveのIssue/PR/branch/head SHA、対象Issueの最新Resume Checkpointを照合する。同一Work Issueに複数active implementation lineage、設計正本の不一致、memory/summaryとGitHub liveの矛盾が1つでもあれば作業を開始せずSTOPしてreconciliationする。Resume GateがPASSした場合のみ、Target Issue / canonical design / active lineage / branch / base SHA / head SHA / current status / last verification / next action / conflictsをResume Certificateとしてユーザーへ提示してから開発を再開する。summary/memoryは候補発見にのみ使用し、GitHub状態の確定には使用しない。

## 10. Dry-run Verification

本ルール導入後、別の新規チャットで実際に「前の作業の続きをして」と依頼し、次を検証する。

- コード操作より先にResume Gateが走る
- 正しいIssue/PR/branch/SHAをlive取得する
- memory/summaryの古い情報をauthorityとして採用しない
- 複数lineageがある状態ではPASSせずSTOPする
- Resume Certificateを提示できる
- reconciliation完了前に新branch/PRを作らない

ユーザー確認後にのみ、開発Freezeを解除する。
