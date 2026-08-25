# AI共通作業規則

このリポジトリで作業するすべてのAIは、以下を必ず守る。

## 日本語のみ使用

自然言語として生成する文章は、すべて日本語にする。

対象:
- コミットメッセージ
- Issueのタイトル・本文・コメント
- Pull Requestのタイトル・本文・コメント
- コードレビューの要約・指摘・提案
- 設計書・運用書・作業記録・チェックポイント
- ユーザー向け報告
- AI間の引き継ぎ文
- プロンプト内の説明文
- エラーメッセージを新規に設計する場合の説明文

英語の自然文、英語の見出し、英語の定型句を新規に作成しない。

次は機械的識別子なので例外とする:
- ソースコード上の識別子
- クラス名・関数名・変数名
- API名・SDK名・モデル名・製品名
- ファイル名・パス・ブランチ名
- SHA・ID・URL
- 外部仕様で固定された列挙値・JSONキー・プロトコル値
- 外部ツールが返した生ログや原文エラーを証拠としてそのまま示す必要がある場合

例外の識別子や原文を説明するときの文章は日本語にする。

## AI別の適用

- ChatGPT: 作業報告、Issue/PR操作、設計、コミット文を日本語にする。
- ローカルCodex: 実装説明、コミット文、PR文、修正報告を日本語にする。
- GitHub Codex Review: レビュー要約、指摘、修正提案を日本語にする。
- Gemini: 構造化レビューの文字列フィールド、要約、指摘、根拠、修正提案を日本語にする。
- 将来追加するAI: 同じ規則を既定で継承する。

## Git運用

- V2の通常マージは履歴上で合流するマージコミット方式を用いる。
- マージ済みブランチへ追加コミットしない。
- 追加修正はマージ先最新から新しいブランチを作る。
- 履歴を動かすためだけの空コミット、一時ファイル、仮文字追加を禁止する。
- コミット前に差分、対象ブランチ、変更ファイルを確認する。
- コミット後かつpush前に、コミット内容と親SHAを再確認する。

## GitHub変更安全規則

詳細正本は `docs/architecture/v2/repository_hygiene_and_mutation_safety.md` とする。

- read/search/fetch/list/compareと、create/update/delete/merge/ref move/file writeを明確に分離する。
- Mutation APIを機能確認、接続確認、schema確認、試行目的で呼ばない。
- すべてのGitHub/Git mutation直前に、Repository、Issue、PRまたは対象、target branch、expected HEAD、path/ref、operation、expected deltaを確定する。
- content writeでbranch/refを省略しない。
- `main`、`develop`、`rebuild/v2-foundation`へ直接content writeしない。
- `update_file`やcommit前にcurrent content/treeとの差分を確認し、real deltaが0なら変更しない。
- `NOOP`、`nonexistent`、`.trigger`、`.issue_sync_marker`、一時marker、直後に削除する前提のfileをshared historyへ追加しない。
- CIやreviewを再実行するためだけにrepository contentやcommit historyを変更しない。rerun、reopen、workflow dispatch等の正規手段を使う。
- branch作成前にlinked Issue、purpose、exact base SHA、予定PR base、既存active lineageとの重複なしを確認する。
- PRをmerge/closeしただけでbranch lifecycle完了としない。MERGED、ABANDONED、TEST_ONLYはいずれも証拠記録後のbranch ref削除までを完了条件とする。
- 誤mutationを検知したら追加mutationを止め、live状態を取得し、Issueへ記録してから最小安全手段でreconcileする。事故を隠すためのforce pushや無断history rewriteを行わない。

## 設計と実装

- 設計を先に確定し、その後に実装する。
- Issueが指す正本設計と実装を一致させる。
- 実装変更時は関連設計文書も同時に更新する。
- V2の作業再開時はResume Gateを通し、GitHub live状態を正本として確認する。

## 自律Completion Missionの継続

このリポジトリでAutonomous Completion MissionがACTIVEの場合、
個別のユーザープロンプトを新しい独立Missionとして扱わない。

ユーザーからの修正指示、設計判断、質問への回答、blocker解消指示、
調査依頼、優先順位変更等は、明示的なMission終了指示がない限り、
現在のMissionへの一時的な介入として扱う。

介入処理が完了したら、その介入だけを完了して停止してはならない。

必ず次を行う。

1. GitHub live状態を再確認する
2. Missionの最新Checkpointを確認する
3. current WorkのResume Gateを再確認する
4. blockerが解消したことを確認する
5. Mission stateをACTIVEへ戻す
6. 元のcurrent Workを再開する
7. Work Completion後はdependency-readyな次Workをfresh Resume Gateで選択して継続する

### Missionの終了

Missionを終了できるのは、ユーザーが明示的に次のいずれかを指示した場合だけとする。

- `MISSION END`
- `MISSION CANCEL`
- Autonomous Completion Missionそのものを終了する明示指示

単なる質問、修正依頼、方針回答、調査依頼、
「Aで進めて」「それを修正して」「この方針で進めて」等は
Mission終了として扱わない。

### 一時停止

真のSTOP条件が発生した場合は作業を一時停止してよいが、
Mission自体を終了してはならない。

Mission stateを `PAUSED_FOR_INTERVENTION` とし、
GitHubのMission管理Issueおよび必要に応じてcurrent Work Issueへ
Checkpointを残す。

Checkpointには最低限、次を記録する。

- Mission名
- Mission state
- current Work Issue
- current PR / branch
- exact HEAD
- 完了済み作業
- STOP reason
- ユーザー判断が必要な内容
- 再開後の最初のaction

ユーザーの介入によってSTOP理由が解消した場合は、
その介入処理だけで終了せず、元のMissionへ自動復帰する。

### STOP条件ではないもの

次は通常の作業継続条件であり、STOP理由にしない。

- test failure
- lint / type check failure
- CI failure
- canonical reviewのblocking finding
- 修正可能なbug
- targeted test PASS
- commit完了
- push完了
- PR更新完了
- 個別工程完了
- Work Issue単体の実装完了

修正可能である限りfix / test / review loopを継続する。

### 外部canonical review待ち

`independent canonical review pending` は Human Intervention ではなく、
`PAUSED_FOR_INTERVENTION` / Mission STOP条件として扱わない。

current Workだけを `REVIEW_PENDING` として記録し、Mission stateは `ACTIVE` を維持する。

同一exact HEADについては次を厳守する。

- independent canonical reviewの依頼・要求は1回だけ行う
- review到着確認のためにsleep / retry / pollingを繰り返さない
- 同じHEADへ重複review依頼を投稿しない
- 新しいHEADが作られた場合だけ、新HEADに対するreview依頼を新規に行える

review待ち中に、そのWorkへ依存しないdependency-ready Workが存在する場合は、
GitHub live dependency graphを確認し、fresh Resume Gateを通してそちらを進める。
review待ちのlineageへ無関係な変更を混ぜてはならない。

進められる独立Workが存在しない場合は、その実行runを安全に終了してよいが、
MissionをHuman Intervention待ちへ変更しない。

pending reviewを再確認してよいのは、原則として次の場合だけとする。

- reviewerから新しいreview / notificationが到着した
- 別の有用なWorkが完了した
- dependency判断上、そのreview結果が必要になった
- ユーザーが明示的に状態確認を依頼した

reviewがHOLDの場合は通常のfix / test / new-head review loopへ戻る。
blocking 0の場合はReady / merge / trunk verification / Work Completionへ進む。

reviewerは、同一exact HEADについて確認可能なblocking findingを可能な限り一度のreviewへまとめ、
既に確認可能だった指摘を細切れに後出しして不要なreview cycleを増やさない。

### MissionとWorkの関係

Autonomous Completion Missionは個別Work Issueより上位の継続目標である。

個別Workの完了はMission完了を意味しない。

current Workが完了したらGitHub live dependency graphを再確認し、
次のdependency-ready Workについてfresh Resume Gateを通して継続する。

Missionの最終完了条件は、Mission管理IssueおよびRoot Issueが定義する
全体完成条件を満たした場合だけとする。
