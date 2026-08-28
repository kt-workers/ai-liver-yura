## Repository文章言語ルール

このリポジトリで人間が読むために書く文章は、日本語を唯一の基本言語とする。

対象は次を含む。

- Markdown、README、設計書、運用書、履歴文書
- Issue本文、Issue comment、Checkpoint
- PR本文、PR comment、review説明
- Mission Checkpoint、Resume Certificate
- commit messageの件名と本文
- GitHubのcommit comment
- コード内comment
- docstring
- 人間向けのlog、warning、error説明文
- 設定ファイルやworkflow内の人間向けcomment

英語だけで成立する文章、見出し、説明段落、comment、docstringは作成しない。
既存の英語文章も翻訳対象とし、安全な通常変更で順次日本語へ置き換える。

次のような英語は、日本語文の中で技術用語または一般語として使用してよい。

- `GitHub`、`API`、`Work`、`Issue`、`PR`、`branch`、`commit`、`push`、`merge`
- `PASS`、`FAIL`、`ACTIVE`、`NOT_RUN`、`REQUEST_CHANGES`等のstatus値
- command、file path、SHA、class名、function名、field名
- machine-readable JSONのkey/value
- 製品名、ライブラリ名、protocol名、固有名詞
- 中学生程度の一般的な英単語を、日本語文章の一部として自然に使用する場合
- 外部API等の原文を、原文であることを明示して引用する必要がある場合

技術識別子に英語が含まれていても、説明文章全体は日本語として成立させる。
コードの識別子、schema、protocol値、機械可読値は文章言語ルールの対象外とする。

共有済みcommitのmessageは、このルールだけを理由にforce pushやrebaseで履歴を書き換えない。
編集可能な既存文書、comment、docstring、GitHub comment類は日本語へ是正する。

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
