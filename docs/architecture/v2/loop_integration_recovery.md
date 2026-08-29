# Loop統合と復旧

## 項目ごとの正本

| 項目 | 正本 |
| --- | --- |
| Issue状態 | GitHub上の現在Issue |
| PR / HEAD / 基点 | GitHub上の現在PRとbranch |
| CI | 厳密HEADに対するGitHub Actions証拠 |
| ProjectのStatus / Priority / Area / Issue level / Start / Target | Project #7の現在値 |
| 正本設計 | Repository正本文書のblob identity |
| Work Checkpoint | 遷移、`TaskPacket`、健全性、永続的な経緯 |
| Mission Checkpoint | 現在Workの経緯と次作業 |

Checkpointの値でProject #7が所有する項目を上書きしない。現在の正本と矛盾した場合は現在状態から修復するか、安全側停止（fail-closed）する。

## 復旧順序

変更を伴う遷移は、必ず「再観測 → `WriteIntent` → 現在条件の再確認 → 効果の実行 → 効果の再確認 → Checkpoint → 再観測」の順で実行する。時間超過や異常終了が発生した場合、遠隔対象を再確認するまで効果の成否を確定しない。

初期版では1つの信頼済みホストだけが変更権（mutation lease）を保持する。外部待機は並行して存在してよいが、変更可能な実行対象遷移は同時に1つだけ実行する。複数ホストによる同時能動運転は初期版の対象外とする。

## 実ホストでの対象解決

通常のLoop CLIは、#450の**最新**`Mission Checkpoint`コメントだけを探索記録として使用し、古い解析可能なCheckpointへ遡らない。変更可能なCheckpointは最低でも`current Work`を明示し、PRが存在する場合は`current PR`と観測した厳密HEADも記録する。

Checkpointの対象情報自体は実行上の正本ではない。解析後、CI判定、Codex起動、Ready化、統合、Issue終了、Checkpoint投稿の前に、Work IssueとPR/branch HEADをGitHubから再取得する。CheckpointのHEADと現在PRのHEADが異なる場合は古い情報として扱い、再調整が完了するまで変更しない。

最新Mission Checkpointに明示的な現在対象がない、対象識別情報が不正、またはGitHubの現在状態と再調整できない場合、ホストは型付きの安全側停止結果を返す。過去の完了済みWorkを再実行する危険があるため、古いMission Checkpointへ暗黙に戻ってはならない。

次Workを選択する計画専用Codexは、次回ホスト実行が必要とする`current Work`、PR、HEADの識別情報を明示した新しいMission Checkpointを必ず作成する。

## 統合競合の再調整

PRの統合可能性はGitHubの現在値を正本とし、Ready化または統合変更の直前にも再確認する。PRが`mergeable=false`または`mergeable_state=dirty`の場合、厳密HEADのCIが成功していてもReady化せず、直接統合コマンドへ送らない。

統合競合は、それ自体では人間介入を必要とせず、対処可能な製品作業系列の状態である。ホストはCodexへ1回の限定遷移だけ機能的な再調整を依頼する。Codexは修復方法を決める前に、最新Mission Checkpoint、現在Work/PR、現在基幹、正本設計、依存状態、Work固有の再開確認（Resume Gate）を再取得する。

- 既存作業系列が有効なら、現在基幹をfeature branchへ通常統合し、競合を解消する。
- 正本の再開確認が既存作業系列を廃止対象と判定した場合は、現在基幹から新しい作業系列を作成して識別情報を記録する。

force pushとrebaseは禁止する。再調整遷移内では製品PRを統合しない。必要な設計・コード・テストを更新し、適用可能な機械検査を実行し、通常push後に新しい厳密HEADを再取得して明示的なMission Checkpointを1回記録する。次回ホスト実行が新しい状態を再観測し、CIと統合を通常経路で処理する。

期待HEADを固定した統合コマンドが失敗し、GitHub再確認でも統合競合と確認できない場合、認証情報、権限、通信失敗などをソース競合として誤分類せず、`EXPECTED_HEAD_MERGE_FAILED`を維持する。

## Codexのホスト実行契約

信頼済みホストは、廃止済みまたは互換用の`--full-auto`短縮指定へ依存せず、現在のCLI契約を明示してCodexを起動する。

既定のCodex子プロセスは作業ファイルの編集と検証だけを担当し、`workspace-write`隔離領域で起動する。

```text
codex -a never exec --sandbox workspace-write -c sandbox_workspace_write.network_access=true <instruction>
```

`workspace-write`では`.git`管理情報への書込みが拒否されるため、branch作成、基幹統合、`git add`、commit、push、PR作成、Mission Checkpoint更新などは信頼済みホスト側で実行する。Codexへ`danger-full-access`を与えてGit操作を成立させる方式は採用しない。

`codex --version`の成功だけでは、この実行契約が利用可能という証拠にならない。実製品試験では、子プロセスが割り当てた限定遷移のファイル編集と検証を実際に実行でき、信頼済みホストがその差分を安全にGit/GitHubへ反映できることを証明する。CLI構文不整合、実効読取専用状態、通信不可などで割り当てた処理を実行できない場合は機能停止要因として扱う。

Codex子プロセスへ渡す環境変数は引き続きホスト側で制限する。レビューワー認証情報やデータベース認証情報を子プロセス環境へ追加しない。`LOOP_CODEX_COMMAND_JSON`でCodex起動コマンドを上書きできるが、上書き側も秘密情報境界と作業ファイル編集能力を維持しなければならない。

## 実装処理の進捗再確認

Codexプロセスの終了コード0だけでは`COMPLETED`にしない。実装、CI不具合修正、統合競合再調整を依頼した後はGitHubの現在状態を再取得し、次の両方を確認する。

- Mission Checkpointのコメント識別情報が更新されている。
- 現在PRまたは厳密HEADの識別情報が実際に前進している。

どちらかが変化していない場合は`IMPLEMENTER_NO_PROGRESS`として安全側停止する。これにより、Codex内部で処理が完了していないのにプロセスだけ正常終了し、同一遷移を連続再実行する状態を防ぐ。

## #471基盤統合後の振り分け

PR #477は実ホストLoopを実行可能にする基盤実装である。PR #477の統合だけでは#471の完了証拠にならない。#477が基幹へ入った後も#471はopenのまま保持し、ホストが依存関係を満たした実製品V2 Workを試験対象として選択する。

`current Work: #471`かつ有効なPRなしの状態は、通常実装の続行ではなく**試験対象選択専用状態**として扱う。この状態でCodexへ#471のコード実装を再依頼してはならない。

ホストは#471を完了済みWorkとして計画専用Codexを1回起動し、#462/#471自身とLoop Engineering基盤Issueを除外して実製品V2 Workを選択させる。計画後は最新Checkpointを再取得し、別の製品Workへ`current Work`が移動したことを確認する。

Checkpointは更新されたが`current Work`が#471のままなら、依存関係を満たした製品Workが存在しない待機状態として`PILOT_DEPENDENCY_WAIT`を返す。Checkpoint自体が更新されなければ`PILOT_PLANNING_NO_PROGRESS`として停止する。

## 実行時の可観測性契約

通常CLIは限定遷移中に無反応へ見えてはならないが、既定の端末出力は読みやすく保つ。人間向け進捗、詳細診断、機械可読な完了出力を分離する。

- 既定の標準エラー出力には起動、ログ保存先、主要工程開始、Codex開始/完了、失敗、最終結果だけを簡潔に表示する。
- 成功したGitHub/API子コマンドの反復開始/完了とCodex生出力は永続実行ログへ保存し、既定端末では非表示にする。
- `--verbose`指定時だけ詳細子コマンドとCodex生出力を標準エラーへ表示する。
- 標準出力は最終`HostTransitionResult`のJSON専用とし、スクリプトが決定論的に解析できるようにする。
- 端末表示量に関係なく、すべての実行で安全な子プロセス出力を`logs/loop_engine/`配下へ保存する。
- 秘密値、`.env`内容、レビューワー認証情報、データベース認証情報、除外後環境全体、指示文や秘密相当値を含む完全な引数列はログへ出さない。

失敗時は既定端末へ工程と終了・結果コードを表示し、詳細ログ保存先を案内する。可観測性は実ホスト運用性の一部だが、通常の低レベル通信で操作者端末を埋めてはならない。

## 厳密HEAD CIの判定順序

CI証拠は、まず期待する現在HEADへ結び付けてから実行状態を解釈する。観測した実行が別HEADのものなら、その実行が`queued`または`in_progress`でも`STALE`とする。古いHEADの待機実行によって現在Workを誤ってCI待機として扱ってはならない。

`evidence.head_sha == expected_head_sha`を確認した後にのみ、`queued`/`in_progress`を`YIELD_EXTERNAL`、`success`を`PASS`、その他の終了結論を`FAILED`として扱える。

## 待機と完了

`CI_PENDING`、`REVIEW_PENDING`、`HUMAN_VERIFICATION_PENDING`、認証情報、外部提供元、Project、データベース障害は型付き待機として扱う。独立して進められるWorkがあれば進め、なければ高頻度再試行せず実行機を外部待機へ移す。

レビュー待ちや外部提供元側の`NOT_RUN`だけでは完了停止要因にならない。レビュー指摘は、現在のMission方針で決定論的または再現可能な機能失敗が証明された場合だけ停止要因とする。

`MISSION_COMPLETE`には、Root #317、必須Work/Integration、人間・システム確認、実行起動・継続・再起動・安全終了、機能を停止させる競合0件の明示的な証拠が必要である。候補0件やWork 1件の統合だけでは不十分とする。

## 統合試験の受け入れ条件

統合試験では、新規Workから通常統合、機能不具合修正、待機と再開、古いCI・レビューの拒否、push・review・merge後の異常終了復旧、DB縮退、Project #7障害、Project #6拒否、自己改善の重複防止、`SIGINT`、競合する作業系列の停止、誤完了防止を検証する。

制御された偽接続口による統合試験は必要だが、#471完了には十分ではない。通常Loop CLIから到達できるホスト構成をRepositoryに備え、実際の事前確認（Preflight）、観測（Observe）、監督（Supervisor）、実装（Implementer）、検証（Verify）、Checkpoint境界で、人間が`TaskPacket`やレビュー指摘をエージェント間転記せずに限定遷移を実行できることを証明する。
