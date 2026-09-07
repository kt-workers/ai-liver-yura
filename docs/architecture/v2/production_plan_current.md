# V2 現行製造計画

状態: #550 改訂5 / 本体優先と外部機能・管理残件の分離（2026-09-07）

初回計画確定時の製造起点（履歴）: `rebuild/v2-foundation@e054f21595c78052c6a791e6af7758ad51e1fd7c`

このSHAを現在の本流として固定しない。再開時にはGitHub上の本流・Issue・PR・最新Checkpointを取得する。第2・3節はPR #556で計画を確定した時点の成果と工程の記録、第4節は当時の管理課題と参照先である。現在の製造判断には第5・6節を適用する。

## 1. Authority

この文書は、D10完了後のGitHub live stateを再監査して確定する**current production execution plan**である。

優先順位:
1. current `docs/architecture/v2/**` canonical design
2. GitHub live Issue / PR / branch / merge / exact HEAD / Human Verification evidence
3. 本書 `production_plan_current.md`
4. D10時点の元工程を保存する `production_sequence_authority.md`
5. 2026-08-13時点の履歴資料 `project_sync_manifest.md`

`production_sequence_authority.md` はD10で保存したoriginal sequence baselineであり、Post-D10 state reconciliation後のcurrent execution順を単独では決めない。`project_sync_manifest.md` に残るProject #6、旧Status、旧Start/Targetはすべて履歴情報である。

current Project日程AuthorityはProject #7 `プロジェクトゆらv2`。Project #6は変更しない。

## 2. 初回計画確定時の成果照合（履歴）

Issue stateそのものを完了証拠にせず、Issue完了条件、canonical、current trunk、関連PR、merge ancestry、CI、必要なHuman Verificationを再照合した。

### 完了済みとして維持する成果

Foundation、Brain、Speech、Memory、Body基盤、Infrastructure、Streaming等の既にcurrent trunkへ統合済み成果は再実装しない。

追加でstale open stateを整合した:
- #341 Body Integration: PR #541 merge + Human Verification PASS → completed
- #346 Avatar: PR #542 merge + Human Verification PASS → completed
- #353 Development Tooling: PR #456 merge、current trunk ancestry確認 → completed
- #445 Design Completion Gate: D10 PR #502 merge / blocking design gap 0 → completed
- #545 Browser verification incident: root causeを#546へ分離し再Verification PASS → completed
- #546 Body Solver overshoot bug: PR #548 merge + Human Verification PASS → completed

### historical / verification-only

- PR #544: closed / unmerged。#341/#346のverification-only lineageであり、production roadmap・Resume starting point・dependency completionの根拠には使用しない。
- V1/legacy lineage: #317/#318のMigration Matrix方針どおりproduct codeをV2へ直接merge/cherry-pickしない。

### 実装済みだがVerification残

- #365 Game Skill Runtime: production implementationはcurrent trunkへmerge済み。再実装しない。ただしcanonicalが要求する実ゲーム/実操作Human Verificationは未完了なのでIssue completionは未達。
- #365はD8でPlugin Integration #344をdirect dependencyから外している。Game Skill RuntimeそのものはPlugin 0件でも成立する。

## 3. 初回計画確定時の製造・検証の順序（履歴）

### Production implementation lane

1. **#344 Plugin Integration**
   - direct dependencies #334 / #343 は完了済み。
   - current trunkにPlugin Integration production implementationは未確認。
   - #550 merge後にfresh Resume Gateを行い、PASSした場合のみ次production implementationとして開始する。

2. **#351 GUI / Admin**
   - #344 と完了済み #341 をdirect dependencyとする。
   - #344 completion後にResume Gateする。

3. **#352 Validation Labs**
   - broad production-path Harnessを所有する。
   - direct dependencyに#365を含むため、#365 Human Verificationを含むWork completionを確認してからfull completionへ進む。
   - #427 Semantic Verification Labや#434旧diagnostic lineageを重複実装しない。

4. **#360 System Integration**
   - 各段階に必要な本体成果と検証証拠が揃い次第実施する。#351の完了は本体統合・本体完成の前提ではない。
   - GUI接続の検証だけは#351の公開面・構成・品質条件を前提とし、任意機能側の結果へ分ける。#352や#365の証拠待ちも、その証拠が必要な段階へ限定する。必要な能力・品質の最終確認は省略しない。
   - Root #317 completionへ接続する最終production integration lane。

### Human Verification lane

- **#365 Game Skill**: production implementation済み。実ゲーム/実操作Human Verificationを残作業として扱う。
- **#434 Speech Character Quality**: direct Speech dependenciesは完了済み。formal Human Verification開始前に、actual Presentation、source-grounded Human context、exact provenance/export surfaceがcurrent trunk上で成立することをfresh Resume Gateで確認する。必要surfaceが未実装なら#352 owner責務へ戻し、#434専用の別production semantic pathを作らない。

Human Verification待ちを理由に、依存しないproduction lane全体を停止しない。

## 4. 管理課題の由来と現在状態の参照先

### #509 Merge Gate

PR #556での計画確定時には、ブランチ保護と必須検査の強制が未設定だった。その後、#509の最終完了記録で設定・再取得を含む合格が記録された。過去の未設定状態を現在の停止理由として使わない。

各PRの取り込み時は現在の保護設定・必須検査・本流との整合を再取得して検証する。#509の過去の合格だけで現在の検査を省略しない。

### #425 Project #7 schedule

本書でcurrent dependency graphを確定後、#425をAuthorityとしてProject #7のStart date / Target dateをlive stateから再計画する。Issue本文やProject #6の日付をコピーしない。

### #549の監査完了

対象本流`8a8b4cecdc77225139e3af836d71b6c8ff62ebd2`の報告`549-audit-8a8b4cec-r2`は独立レビューPASS。全71件の由来、設計と本文の依存、問題の所有者への返却、#317／#207への共有を照合し、completedへ変更した。製品修正の未達条件は各所有者に残す。

## 5. 本体優先の製造順と未達条件

ユーザーが2026-09-07に確定した優先順位を適用する。意思はその時の思考・判断から生じ、実行可能性は接続された能力による。配信・ゲームの選択を本体の固定方針・専用機能として追加しない。本体は能力認識、判断・目標・計画に基づく汎用要求、実行結果の次の思考への返却を所有する。能力未提供は既存の型付き利用不可・失敗に閉じる。

### 本体の残件

| Issue | 保持する成果 | 本体完成に必要な未達条件 |
| --- | --- | --- |
| #329 | 活動の事前確認・実行・効果事実と未確認効果の区別 | 計画と汎用要求の接続、結果の評価・判断への返却 |
| #333 | 注意・会話順序・割込みの所有者、PR #585 | 現在状態からの適格性、判断・発話への継続接続と割込み |
| #334 | 処理登録・版伝播・取消回収、最小入力意味起動 | 現在文脈、評価、注意、判断、目標・計画・活動、発話、記憶の本番所有者の具体結合 |
| #361 | 目標からの計画生成・検査・確定 | 計画全体への明示的承認範囲内での手順進行、命令発行、上限付き再試行、再計画要求 |
| #359 | 保存契約、PR #589で本流採用済みのPostgreSQL実装・実DB検証 | 記憶保存と所有者による目標復元の本体接続、別プロセス再起動・失敗・停止 |
| #352 | PR #590の本番所有者を使う検証基盤 | 修正HEAD 511d0f03の採用、本体の未接続経路と実発話品質の証拠 |
| #360 | 段階統合の契約、PR #582の本体独立起動検証 | 通常認知全体・汎用活動・発話・記憶復元・並行動作・正常停止の段階接続と最終検証 |
| #434 | 発話文単独の診断証拠と正式品質の区別 | 実音声・実提示、状況に由来する文脈、同一来歴を用いた自然さ・ゆららしさの人間確認 |

本体残件は8件。Closedであった#329／#333／#334／#361は後発の未達条件を保持して再開する。既存成果の合格を取り消す意味ではない。最小起動だけを本体完成としない。

### 進める順序

1. 受領済みの対象コミット別レビューを記録する。#589は本流9ec6893475328578e2b3a0513bcf67c3d8c33f75へ採用済み。#590の修正は511d0f03でCI成功・独立レビュー待ち。本体の保存復元接続と独立に進められる。
2. #334／#361／#329の計画全体への明示的承認を設計で具体化する。承認範囲、手順依存、命令発行権限、能力・版の再検査、再試行上限、再判断・再計画への返却を既存所有者に割り当てる。検証基盤で補作しない。
3. #333の本体接続と#334の具体結合、#359の保存復元を、各公開契約と必要成果が揃った範囲から進める。全Issueの一律完了待ちにしない。
4. #352で模擬提供先による汎用能力の成功・利用不可・失敗・取消・結果返却を検証し、#360の本体段階結合へ接続する。遅い処理中の入力・発話・身体・背景処理の継続と正常停止を検証する。
5. 実発話と文脈・来歴が揃った段階で#434の人間による品質確認を実施し、機械検査と別軸で本体完成を判定する。

### 後回しの外部機能

#347の配信、#365のゲーム技能、具体プラグインの追加・接続、GUIの製造・画面品質、これらに固有の実サービス・実機接続検証は後続とする。#333／#352／#360内の同種条件も後続へ分ける。既存成果・未完了条件を削除したり、完了扱いにしたりしない。外部機能の不在やレビュー待ちは本体製造・本体完成の一律停止条件ではない。

実発話の品質は本体側に保持する。模擬提供先の成功を実サービス品質へ昇格しない。#586の性能試験・改善は本体実装完了後の別工程であり、今回は着手しない。

### 管理残件と集計

#384の文章日本語化・履歴整理と、今回の再計画を採用する#550を管理残件として分ける。#384の管理作業は本体製造を止めない。最終履歴再構成は機能修正と日本語化の完成後とし、新系列の木・CI・参照整合を確認する前に旧参照を削除しない。

#549完了と#550再開を反映すると、既存の全71件中の残件は12件。本体8件、外部機能2件、管理2件である。GUIなど既存の集計対象外も後続の未完条件として保持する。「8件＋#384の9件」に機械的に合わせて#550を隠さない。#550採用完了時には管理残件を1件減らす。

## 6. Resume rule

各Work開始・再開前に必ずGitHub liveで次を再取得する。

- Target Issue
- canonical design
- active implementation lineage
- branch
- base SHA / head SHA
- competing lineage
- current CI / review / Human Verification evidence
- current trunkとのancestry / diff
- next action

Resume Certificate PASS後だけimplementation/reconciliationへ進む。summary / memory /古いCheckpointだけでcurrent stateを確定しない。

## 2026-09-07 本体成果の結合と採用

#550の計画改訂はPR #591で本流採用済み、管理Issueも完了している。現在の残件は全71件中11件、本体8件・外部機能2件・管理#384の1件である。本体8件の完成条件は前節を維持する。

以下の独立レビューを、記載した対象HEADの変更範囲に限定して受領した。

| PR | レビュー対象HEAD | 判定 |
| --- | --- | --- |
| #582 | 151052426a59cf25c6cacb23eec7147133ea23a8 | PASS |
| #590 | 6ed536eac8508f344a71ea7563a9c847f2c911b0 | PASS |
| #593 | 82507e868392b9c6624793e7eac57f1a7419c71f | PASS |
| #594 | 61f72911ea56b0aa20a3e5aa97006bcf7b5bcfae | PASS |
| #595 | fd0d8d676303cf434ffae53f61eeca70e08534ea | PASS |
| #596 | 30104f47466611e2d30a07a8dd20360b8229a3ad | PASS |

最新本流の包含を必須とする保護設定を維持する。検証基盤#590は本流 `0ad39a9efbca5ec9268851a31f89991c108b06d5` へ採用した。残る成果は既存の#582の本体結合枝へ通常マージする。元の作業枝・コミット・設計・試験を保持し、再実装や履歴の書換えをしない。結合後の内容を実PostgreSQLを含む全体試験で検証し、新HEADの必須CIと独立レビューを通して採用する。元PRのPASSを結合後HEADのPASSへ読み替えない。

この採用は本体結合の前提を揃える段階である。次に計画進行所有者を通じて、現在計画の照合、承認登録、手順の開始予約、完了評価による依存解除、再開・再試行・再計画要求を接続する。認知・注意・判断・発話・記憶復元・並行動作・正常停止の本体全経路と、人間による実発話品質は未完のまま追跡する。後回しの外部機能を再優先化せず、#586には着手しない。

### 2026-09-07 結合成果の採用後と新規手順進行

#582の結合後HEAD `b7afba93ef31f5a239a2fb9423800c553fbfb367` に対する独立レビューPASSを受領し、本流 `9276bcf211ded3218a55209e018aff1cd9edc5ff` へ通常マージした。採用後の内容は対象HEADと差分0。上記の結合採用待ちは解消し、元PR #593・#594・#595・#596もMERGEDへ収束した。本体残件8件の完成を意味しない。

#334は既存の`feature/334-approved-plan-progression`を継続する。登録した現在計画への承認、依存手順の開始予約、活動所有者の事実取得、判断所有者の完了評価による依存解除、承認範囲内の再試行、取消・停止時の実処理回収を製造する。計画・判断・活動を新しい正本へ置き換えず、現行所有者の公開契約へ接続する。

既存活動の再開と通常認知経路からの呼出し、注意・発話・記憶復元・並行動作・正常停止の全体検証、人間による実発話品質は残る。現タスク番号 #334／残タスク数11／全タスク数71。本体8件、外部2件、管理1件を維持し、#586には着手しない。

### 2026-09-07 計画進行・既存活動・記憶接続の採用後

#597は本流`f138d2deb5fc09d9dcaa14807631756a94bafb11`、#598は`f497198762d0ccca8c76159654da08662c82a988`、#599は`d7c33e77fbc0095c917c20552706a605f172934b`へ採用済み。各対象HEADの独立レビューPASSと採用前の必須CI成功、採用後の内容一致を確認した。新規手順の進行、同じ進行所有者の既存活動への観測接続、記憶所有者への非同期委譲と回収を保持する。

次の#334は、目標・活動所有者からの参照文脈と採用直前の現在版取得を本体へ接続する。既存の目標選択方針と実行事実を使い、投影世代と元の所有者の版を区別する。最近の発話・判断・記憶根拠の供給、通常認知の具体結合、保存復元・並行動作・正常停止の全体検証、#434の人間確認は未達として残す。現タスク番号 #334／残タスク数11／全タスク数71、本体残件8件を維持する。外部機能・GUIは後回し、#384は管理残件、#586には着手しない。

### 2026-09-07 入力参照の採用と永続化起動の結合

#600のHEAD `dba1488b36ea9fdcbff04e3d149824c3f2448e1d`への独立レビューPASSと必須CI成功を確認し、本流`a02c203687a589d66d6d3be83812b08fe2a9c2f1`へ採用した。採用後の内容は対象HEADと差分0、起動・参照文脈36試験も成功した。

次の#359は既存枝`feature/359-core-goal-persistence`を継続し、復元した目標と同じ入口を入力参照へ接続する。記憶操作、起動時の障害報告、再取消でも回収する停止を既存所有者で構成する。接続先の配備設定、通常認知の全操作、評価・注意・判断・発話と並行動作の全体検証、#434の人間確認は未達として保持する。現タスク番号 #359／残タスク数11／全タスク数71、本体残件8件。外部機能・GUIは後回し、#384は管理残件、#586は未着手。

### 2026-09-07 通常認知結合で発見した文脈更新境界

#602は独立レビューPASS・必須CI成功を確認し、本流`8890b2f97e3d16f2238f1c18623a9df70f03cd19`へ採用済み。採用後の内容一致と起動・復元43試験成功を確認した。

#334の通常認知結合で、深い評価の入口が状態の由来と今回の入力文脈の一致を要求し、目標などによる文脈更新後に評価を開始できない不整合を再現した。#327の既存成果は保持し、所有者の後発未達条件として再開する。状態の由来を付け替える構成側の回避策を作らず、既存枝`fix/v2-appraisal-d10-decay-policy`で設計・実装・検証を是正する。

現タスク番号 #327／残タスク数12／全タスク数71。本体残件9件（従来8件に#327の後発是正を追加）、外部2件、管理#384の1件。#327の是正採用と完了条件再照合後に残数を戻す。通常認知全体の未達条件は維持し、外部機能・GUIを再優先化せず、#586は未着手。

### #603採用と現在状態からの評価接続（2026-09-08）

#603の対象`9849cce0`への独立レビューPASSと再CI成功を受け、本流`ce15cbb3`へ採用した。対象との内容差分0、本流の関連83試験成功、既存系統の包含と完了条件を再確認して#327をClose・Doneへ戻した。後発是正1件を解消し、残11件／全71件、本体8件・外部2件・管理1件とする。

#334は既存`feature/334-approved-plan-progression`を継続する。関連7枝は現在本流に対する固有コミット0で、重複系統を作らない。次の接続は現在の入力参照と状態所有者を深い評価・同時確定へ渡す入口である。第24節を先に具体化し、検証基盤の固定状態を本体の現在状態として使わない。全役割の起動設定、注意・判断・目標・活動・発話・記憶の通常認知結合と全体品質検証は引き続き未達。外部機能・GUIと#384の後回し条件を保持し、#586は着手しない。

### #604採用と定型評価・注意接続（2026-09-08）

#604の対象`54875186`への独立PASSとReady変更後の必須CI成功を確認し、本流`939c034a`へ採用した。内容差分0、本流関連121試験成功。#334は既存系統を継続し、本体結合契約第25節を先に具体化する。定型評価も同じ状態・評価事実の確定へ接続し、注意の選択元と現在状態の由来を分けて搬送する。注意所有者の優先度や割込み判断を構成側で代作しない。残11件／全71件、本体8件・外部2件・管理1件を維持し、通常認知全体は未達、#586は未着手である。

### #605採用と実行判断への接続（2026-09-08）

#605の対象`0affc12a`への独立PASSと再CI成功を確認し、本流`9cf6ac72`へ採用した。内容差分0、本流関連139試験成功。既存#334系統で設計第26節を先に具体化し、注意搬送と供給元の型付き根拠から既存実行判断へ接続する。確定前に現在の根拠・必須要件を再取得し、候補申告から要件を代作しない。供給元の具体登録、全役割の起動と判断後の分岐、全体品質は未達。残11件／全71件、本体8件・外部2件・管理1件、#586未着手を維持する。
