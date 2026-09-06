# V2 現行製造計画

状態: #550 改訂3 / 本体と任意GUIの完成条件の分離（2026-09-06）

製造起点: `rebuild/v2-foundation@e054f21595c78052c6a791e6af7758ad51e1fd7c`

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

## 2. Post-D10 state reconciliation result

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

## 3. Current production / verification graph

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

## 4. Management gates

### #509 Merge Gate

#509は未完了。

current `rebuild/v2-foundation` はbranch protection / required status checksが強制されていないため、#509 Acceptanceを満たしていない。これは#344の設計・実装着手そのものとは分離できるが、**#344を含む次のproduct PRをproduction trunkへmergeする前に解消する**。

### #425 Project #7 schedule

本書でcurrent dependency graphを確定後、#425をAuthorityとしてProject #7のStart date / Target dateをlive stateから再計画する。Issue本文やProject #6の日付をコピーしない。

### #549 cleanup

#549はblocking contamination 0の監査結果を保持しつつ、#207・各Issue・文書に残るProject #6 / 旧V1表記を歴史資料として明確化するcleanup管理のためopenを維持する。

## 5. Next action

PR #556による旧計画の確定と、その後の#344・#561等の成果は履歴として保持する。以下を現行の製造判断とする。

1. 本体の各Work・統合段階は、その責務に必要な成果・公開契約・証拠を現在状態から照合して再開する。#351を一律に待たない。
2. #351は任意GUIの既存系統で継続する。未完了やレビュー待ちを本体製造の停止理由にしない。
3. #352は必要な本番経路の検証基盤を整備する。実ゲーム・音声・画面などの証拠は対象別に判定し、実施していないものを完了扱いにしない。
4. #360はGUIなしの本体統合と任意GUI接続を区別する。Root #317とMission #450の本体完成監査はGUI全完成を要求しない。
5. 任意GUIの品質確認と未完了項目は#351・#345に残し、本体完了時に削除・完了扱いにしない。

依存は「本体の製造・稼働に必要」「任意機能の接続に必要」「特定の検証証拠に必要」の三種類へ分類する。#351は二番目に属する。実機を要するゲーム・音声等の品質確認は三番目の前提として保持する。これは本体が持つべき能力を削る分類ではない。

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
