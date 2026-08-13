# 「プロジェクトゆらv2」仕様・運用ルール

Status: Canonical
Effective: 2026-08-13
Project owner: `ktan514`
Project number: `7`
Repository: `ktan514/ai-liver-yura`
Root Issue: #317
Management migration: #367

## 1. 目的

GitHub Projects v2「プロジェクトゆらv2」は、AI VTuber「ゆら」の再スタート後のV2開発だけを管理する。

- Owner: `ktan514`
- Project番号: `#7`
- URL: `https://github.com/users/ktan514/projects/7`
- Repository: `ktan514/ai-liver-yura`
- 公開範囲: Private

旧Project #6はV2の新しい管理正本として使わない。

## 2. Membership invariant

Project #7のmembershipはRepository label `v2`で判定する。

**`v2` labelあり = Project #7管理対象。**
**`v2` labelなし = Project #7管理対象外。**

Issue名、PR名、branch名、過去Project membership、旧V2という文字列だけではV2対象と判断しない。

- V2 Issueには`v2` labelを付ける
- V2 Pull Requestにも個別に`v2` labelを付ける
- Issue labelがPRへ自動継承されるとは考えない
- Project Auto-add workflowは`label:v2`を条件とする
- `v2` labelがないProject itemはProject #7 membershipから外す
- membershipから外す際、Issue / PR本体をclose/delete/archive/編集しない
- Project itemのarchiveではなく、V2専用Projectからmembershipを除去する

このinvariantはProject #7のscope判定で最優先する。

## 3. 管理対象

次だけを管理する。

- V2アーキテクチャに基づいて新たに計画した作業
- V2の設計、実装、調査、検証、統合
- `v2` labelを持つV2 Issue
- `v2` labelを持つV2 Pull Request
- V2の依存関係、優先度、担当ロール、日程、実環境確認

初期プロジェクトの作業をそのまま移行・継続する場所ではない。V2として明示的に再計画されていない旧Issue / 旧Pull Requestは対象外。

## 4. 参加者と担当ロール

参加者:

- `ktan514`: 人間
- `ch4t9pt`: AI（Codex / ChatGPT）

担当はGitHub AssigneesではなくProject専用field `担当ロール` で管理する。

### AI作業

現在の担当者: `ch4t9pt`

- 要求整理
- Architecture / detailed design
- 実装・製造
- 自動テスト
- 静的解析
- 調査
- Code review
- Documentation
- Pull Request準備

### 人間確認

現在の担当者: `ktan514`

- Render実動作確認
- Local実動作確認
- Browser / GUI / Live2D / 音声 / 外部サービスを使う確認
- 人間による最終使用感・挙動判断

### 共同判断

`ktan514` + `ch4t9pt`

- 仕様決定
- 優先順位決定
- 重大Architecture変更
- 責任境界変更
- 大きなtrade-offを伴う判断
- Project方針変更

GitHub標準Assigneesと`担当ロール`は別物。Project管理の都合だけでIssue / PR Assigneesを変更しない。

## 5. Status

- `Backlog`: V2作業候補。着手条件未成立を含む
- `Ready`: 仕様・責任範囲・依存関係が整理され着手可能
- `In progress`: 設計・実装・調査・自動テスト等を進行中
- `Review`: PR / Design / Implementation result等を確認中
- `Verification`: Render / Local等で人間実動作確認待ち
- `Blocked`: 依存作業・判断・権限・外部サービス・環境待ち
- `Done`: 実装・自動テスト・必要な実動作確認・Review・必要なmergeまで完了

## 6. Statusと担当ロール

原則:

- Backlog → `AI作業`
- Ready → `AI作業`
- In progress → `AI作業`
- Review → `AI作業`
- Verification → 実動作確認が必要なら `人間確認`
- Blocked → blockerを解除する作業 / 判断の担当ロール
- Done → 担当作業完了

Verification FAIL:

1. `In progress`へ戻す
2. `AI作業`へ戻す
3. `ch4t9pt`が修正・自動テスト
4. 再び実環境確認が必要なら`Verification` + `人間確認`

実動作確認が必要な作業をReviewから直接Doneにしない。

## 7. 管理field

### Priority

- `P0`: V2成立 / 主要責任境界に不可欠
- `P1`: 主要機能 / 品質に必要
- `P2`: 比較的低優先の改善

### Issue level

- `Parent`
- `Work`
- `Integration`
- `Management`

### Area

原則としてIssue本文に記載されたV2の`Area:`と一致するProject optionを使用する。

管理Issueのcanonical special case:

- #317: `Management`
- #318: `Management`
- #319: `Management`
- #367: `Management`

#317のPriorityは`P0`、Issue levelは`Management`をcanonicalとする。

旧Project #6のbroad Area taxonomyをProject #7へ自動流用しない。

### 日程・見積もり

- Iteration
- Start date
- Target date
- Size
- Estimate（必要時）

日程・見積もりを推測だけで設定しない。Issue / canonicalに根拠がない値は空欄のままにする。

現時点ではIteration / Size / Estimateはcanonical未設定のため空欄を維持する。

## 8. 完了条件とVerification

コード実装 / 自動テスト成功だけで常にDoneにはしない。

以下の実環境確認が必要なら`Verification`を経る。

- 実LLM
- TTS / VOICEVOX
- Avatar / Live2D
- GUI / Browser
- Render
- Streaming
- Game
- 外部サービス
- Local実行環境

人間実動作確認未完了なら、その事実を明記しDoneと主張しない。

## 9. 安全なProject操作

1. `gh` commandを使う前に`ktan514`へ認証確認の許可を求める
2. GitHub accountを勝手にswitch / logoutしない
3. Project Owner / number / URL / Project IDを毎回live確認
4. field ID / option IDを変更前にlive再取得
5. existing Project item duplicateを確認
6. mutation後Project liveを再取得して検証
7. Project都合でIssue本文 / Assignees / Milestone等を勝手に変更しない
8. Issue / PR変更を伴う場合は対象と変更内容を事前明示
9. source code / branch / PR state / merge stateをProject整備の一環で勝手に変更しない
10. APIで確認できないView / Workflow設定を確認済み扱いしない
11. `v2` labelがないitemをProject #7へ残さない
12. scope外itemをProjectから外してもIssue / PR本体は変更しない

## 10. ChatGPT / Codex作業報告

最低限:

- 対象Issue / PR
- Current Status
- 担当ロール
- 実施変更
- 検証結果
- 人間実動作確認の要否
- 残作業 / 判断

## 11. Current migration gate

2026-08-13にV2 canonical architectureはユーザー承認済み。

Project #7管理基盤への切替 #367 が完了するまで、新規product implementation lineageの開始を一時保留する。

2026-08-13 Phase A auditではProject #7に118 itemsあり、V2 scope 51件と`v2` labelのないscope外67件が混在していることを確認した。scope外67件はmembership invariantに従いProject #7から除去する。

Auto-add workflowはenabledまではAPI確認済みだがfilterをAPI確認できない。`label:v2`であることを人間UI確認してからscope cleanup mutationを行う。

#367完了後、#318 old lineage整理と最初の実装WorkのStart Gateへ進む。
