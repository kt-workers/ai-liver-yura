## 実装優先・親Issue単位Gate

2026-09-08の最新ユーザーAuthorityとして、製造方式をimplementation-firstへ変更する。運用の管理Authorityは#550、現在作業の記録は#450、索引は#207とする。過去の工程指示と競合する場合は本節を優先する。製品の責務・公開契約・最終受入条件の意味は変更しない。

ここで「親Issue」は、設計・実装・テスト等の内部作業を束ね、production plan上で1タスクとして数えるIssueを指す。Projectの分類値`Parent`と同義ではない。正式Gateはこの製造Issue単位とし、内部の設計、型追加、実装、test追加、docs更新、bug fix、checkpointごとに増やさない。本体残件23 Issueなら各正式Gateは原則最大23 Issue分とする。

### 工程と実装中の疑義

原則は `Design completed → Implementation → Test / Verification → Fix → Acceptance` とする。設計採用済みのIssueは実装を完走する。canonicalの不自然さ、contract不足の疑い、concurrency懸念、Owner境界の疑い、設計バグ候補は記録し、実装完了後のTest工程で実証・修正する。`DESIGN_BUG` / `CONTRACT_GAP`候補の発見だけでSTOPし、別Design Issue・Design PR・review・mergeを経て実装へ戻る通常運用は禁止する。

実装中の例外的STOPは次に限定する。

- current canonicalではコードとして一切実装不能。
- ユーザーの仕様選択なしには挙動を一意に決められない。
- competing active lineageが存在する。
- branch・base・HEADが不整合。
- destructive Git操作が不可避。
- secret漏洩リスクがある。
- scope外の破壊的変更が不可避。

「より良い設計がありそう」「テストで失敗しそう」「別の構造の方が綺麗」はSTOP理由にしない。

### 段階的品質向上

製造時に最初から100点の完成度を要求しない。原則は `Design completed → Implementation（70〜80点を目標に主要経路を完成）→ Test / Verification → 不足の実証 → Fix / Hardening → 90〜100点へ向上 → Final Gate` とする。点数は段階的な完成度の目安であり、試験結果や受入条件の達成率を表すものではない。

実装フェーズでは採用済み設計に従い、主要な正常経路・責務・production wiringをまず完成させる。次の理由だけで実装を止めず、懸念を破棄せずTest finding候補として記録する。

- edge caseがまだ完全網羅されていない。
- より綺麗な抽象化が考えられる。
- defensive validationをさらに追加できる。
- concurrency上の追加検証余地がある。
- 将来のtestで問題になる可能性がある。
- canonicalをさらに精密化できる。
- 実装をもっと一般化できる。

Test工程では正常系に加え、edge case、failure path、concurrency / race、cancellation、stale / supersede、integration boundary、restart / shutdown、contract mismatch、design bugを実際の試験結果で確認し、必要な修正を行う。設計バグも実装不能でない限り実装途中でDesign工程へ戻さず、Test工程で再現・実証してからcanonicalとcodeを同じ修正工程で直す。前述の例外的STOP条件は維持する。

70〜80点を目標とする段階でも、次を意図的に残してはならない。これらは完成度とは別の最低限の安全・事実性条件とする。

- 明白なデータ破壊。
- secret漏洩。
- 取り返しのつかない誤った外部effect。
- dummy / noop / fake successによる完成偽装。
- scope外Ownerへの責務移転。
- 未実装を成功として返すfallback。
- destructive Git操作による進行。

Implementation completionは「全て完璧」ではなく、設計された責務の主要経路がproduction codeとして一通り成立した状態とする。Test completionは実装後の検証で発見した穴を修正し、対象Issueの受入条件を満たした状態とする。Final acceptanceは、本節で定義した親Issue単位の最終pytest / Ruff / strict Mypy / compileall / diff-check、正式CI、独立レビューを通した状態とする。段階途中の完成を最終受入やIssue全体の完成へ読み替えない。

### 全面品質検査・CI・独立レビュー

正式なfull pytest、Ruff、strict Mypy、compileall、`git diff --check`は、製造Issueの実装完了後のTest工程で原則1回とする。設計途中、内部の子作業、各commit、各小変更の定例検査にしない。実装中は具体的な故障原因を切り分ける最小診断を許容するが、全面検査の反復を通常の実装ループにしない。

Test Gateで見つかったfunctional / integration / concurrency failureをdesign bug・code bug・contract bugへ分類し、同じIssueのTest/Fix工程でまとめて修正する。必要なcanonicalとcodeの修正はTest工程で確認された不具合修正として扱い、Design工程への手戻りにしない。修正結果の確認は必要な範囲で行い、未解決の失敗をPASS扱いにしない。

正式CIは `implementation complete → local Test Gate → fixes complete → final candidate HEAD → CI × 1` を基本とし、製造Issueの最終候補HEADに原則1回だけ要求する。実装途中、設計だけのHEAD、各小修正HEADへの定例要求と、同じ内容・目的での不要な再実行は禁止する。branch protection等による自動検査は技術的制約として受け入れ、追加の工程Gateへ数えない。CI failureは同じIssueのTest/Fix findingであり、Design工程へ戻さない。採用時は現在の必須検査と実際のHEADを照合する。

独立レビューは製造Issueにつき原則1回、実装完了・Test/Fix完了・CI候補準備済みの最終段階で依頼する。設計だけ、実装途中、test前の依頼、Design reviewとCode reviewの二重Gate、同じ内容の繰返し依頼は禁止する。findingは同じIssueのFix工程で修正し、HEAD更新だけを理由に追加の独立review cycleを自動要求しない。ユーザーが明示的に再レビューを要求した場合は別とする。修正前のreviewを新HEADへの承認と偽らず、findingへの対応と検証証拠を記録する。

### 作業系統とIssue分割

原則は `1 Issue → 1 active implementation lineage → 必要なcanonical調整 → implementation → tests → 1 final PR` とする。同じ製造Issueの設計と実装を別PRへ分け、設計だけのCI・review・merge・fresh Resume Gateを挟む通常運用は禁止する。既に#630/#632で分離済みの歴史・採用成果は保持し、履歴を書き換えない。

新Issueへ分離するのは、Test工程で確認した問題が別責務・別Ownerであり、独立して完成可能かつ現Issueから独立して延期可能な場合だけとする。「設計に穴があった」だけでIssueを増やさない。既存作業系統の確認・回収義務は維持する。

### Resume GateとCheckpoint

Resume GateはIssue開始、チャット切替後の再開、blocker解消後、外部要因でbranch・PR・HEADが変わった場合に行う。active lineage・base・scopeが変わらない同じIssue内では、Design採用・Implementation・Testへの各工程遷移ごとに繰り返さない。

CheckpointはIssue開始、真のblocker発生、implementation complete / Test工程入り、final PR、merge / completion、チャット切替等の重要な状態遷移に限定する。各commit、各test実行、各小修正、各CI stepの定例記録は禁止する。

### #632と#630への適用

#632の設計はPR #633で本流採用済み。次は#632 implementationから実装完了、Test、fixes、最終品質検査、最終CI、独立レビュー、merge / completionへ進む。実装中の設計疑義は原則Test工程のfindingとして保持し、Design工程へ戻さない。#630は#632完成後に再開し、同じ方式を適用する。

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
3. 本書で定める実施条件に該当する場合にcurrent WorkのResume Gateを確認する
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

修正可能である限り同じIssueのTest/Fixを継続する。独立レビューの追加は本書の原則1回の規則に従う。

### 外部canonical review待ち

`independent canonical review pending` は Human Intervention ではなく、
`PAUSED_FOR_INTERVENTION` / Mission STOP条件として扱わない。

current Workだけを `REVIEW_PENDING` として記録し、Mission stateは `ACTIVE` を維持する。

製造Issue単位の最終レビューについて次を厳守する。

- independent canonical reviewの依頼・要求は1回だけ行う
- review到着確認のためにsleep / retry / pollingを繰り返さない
- 同じHEADへ重複review依頼を投稿しない
- HEADが更新されても追加レビューを自動要求しない。再レビューはユーザーが明示要求した場合だけ行う

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

reviewがHOLDの場合は同じIssueのFixと必要な検証へ戻り、追加の独立レビューを自動要求しない。
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
