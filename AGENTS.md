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

英文による説明文・説明段落・comment・docstringは作成しない。
見出しも日本語を基本とするが、一般的な英単語や識別子の使用は次節に従う。
既存の英語文章も翻訳対象とし、安全な通常変更で順次日本語へ置き換える。

### 英語技術語の扱い

英文の禁止は、一般的な英単語や技術語・識別子の使用を禁止するものではない。
`revision`、`version`などの一般的な英単語は、日本語の文章の中で意味が明確ならそのまま使用してよい。特に、コードや公開契約の識別子は翻訳や改名をしない。

説明全体は日本語として成立させる。意味が伝わりにくい専門用語や複数語の概念は、文脈に応じて自然な日本語で説明し、原語の併記は識別・検索・外部仕様との対応付けに必要な場合に使う。

### 更新状態と形式の用語

- 更新状態を表す「版」は「リビジョン」または`revision`と書く。
- 形式・スキーマなどの`version`を表す「版」は「バージョン」または`version`と書く。
- 「期待版」は「期待するリビジョン」など、文脈に合う自然な表現にする。
- 「初版」「出版」など別の意味の語や「世代」は、一括置換せず意味を確認する。
- 過去の引用・履歴記録は書き換えず、現在の説明や指示に使う記述を修正する。
- 表記整理のために既存の識別子、公開API、保存形式、処理動作を変更しない。

次は機械識別子や固有表現として、そのまま使用してよい。

- `GitHub`、`API`、`Issue`、`PR`等の固有名詞・広く定着した名称
- `PASS`、`FAIL`、`ACTIVE`、`NOT_RUN`、`REQUEST_CHANGES`等のstatus値
- command、file path、branch名、SHA、class名、function名、field名
- machine-readable JSONのkey/value
- 製品名、ライブラリ名、protocol名、外部仕様の固定値
- 外部API等の原文を、原文であることを明示して引用する必要がある場合

これらを日本語文章の中で使う場合も、説明文章全体は日本語として成立させる。
コードの識別子、schema、protocol値、機械可読値は文章言語ルールの対象外とする。

既存の英語commit messageは最終状態として残さず、Repository全体の日本語化と機能修正が完了した後に、#384の管理下で現在の完成treeを日本語commit系列として再構成する。
新しい系列のtree、CI、PR、Checkpoint、SHA参照を再照合する前に、旧commit/refを削除しない。
編集可能な既存文書、comment、docstring、GitHub comment類は日本語へ是正する。

## 作業ブランチ系統の整合性

Issueの実装・修正・設計作業を開始または再開する前に、同一Issueに関係する既存PRとbranchをGitHubの現在状態から必ず確認する。
詳細規約は `docs/architecture/v2/branch_lineage_integrity_contract.md` を正とする。

### 作業開始前

1. Issue番号に関連するopen / closed / merged PRを列挙する。
2. Issue番号や既知のbranch名から関連branchを列挙する。
3. 各branchを現在の本流と比較し、固有commitの有無を確認する。
4. 各作業系統を `ACTIVE / MERGED / SUPERSEDED / ABANDONED / HISTORICAL / ZERO_UNIQUE` のいずれかへ分類する。
5. 現在採用する正規作業系統を1本に決める。

`ACTIVE`または未分類で、現在の本流に対して固有commitを持つ作業系統がある場合、同一Issue用の新しい実装branchを作成してはならない。
本流から大きく遅れたbranchでも、まず既存作業系統を継続・整合できるか確認する。

### 「すでに実装済み」と判断するとき

本流に同じ、または似たコードが存在することだけを理由に、古い作業branchを不要と判断してはならない。

必ず次を説明できる状態にする。

- その成果物がどのPR / merge commitから本流へ入ったか。
- 旧branchの変更項目が設計書・試験を含めて全件回収されているか。
- 回収しない変更がある場合、その理由が`SUPERSEDED / ABANDONED / HISTORICAL`としてGitHub上に記録されているか。

由来を説明できない作業系統は未解決として扱う。

### 別の作業系統へ置き換える場合

同一Issueを別branchでやり直す場合、旧branchを放置しない。

- 旧PRへ `SUPERSEDED_BY: #<後継PR>` を記録する。
- 後継PRへ `SUPERSEDES: #<旧PR>` を記録する。
- 旧系統の変更を「後継へ引継ぎ」「不要化」「誤実装」に分類する。
- 新branchを作って同じ機能をゼロから再実装することを第一選択にしない。

既存branchを継続できる場合は、rebaseやforce pushで履歴を作り替えず、必要に応じて現在の本流をそのbranchへ通常mergeして整合する。

### 次工程・Issue完了前

次のIssueへ進む前、およびIssueを`completed`へ変更する直前に、同一Issueの全PR・branchを再列挙する。

次のいずれかがある場合は次工程へ進まず、Issueも完了にしない。

- 未分類の作業系統が残っている。
- 別の`ACTIVE`作業系統が残っている。
- 現在の本流に対して固有commitを持つ未マージbranchに、明示的な処理理由がない。
- 取り込み済みと判断した成果のPR / commit由来を説明できない。

Codexへ作業を依頼する場合も、この確認を省略してはならない。Codexへの指示には、新規branch作成前に同一Issueの既存作業系統を確認し、未解決の固有commitを持つbranchがあれば新しいbranchを作らないことを含める。

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
