# Loop自律実行機

## 継続実行するホストコマンド

`python -m tools.loop_engine`は信頼済みホスト上で動く**継続実行型のMission実行系**である。内部の制御遷移（control-plane transition）は引き続き1回ごとに範囲を限定する。

`Preflight → Observe → Reconcile → Resume Gate → Select → Plan/Execute/Wait/Integrate → Readback → Checkpoint`

安全な遷移が1回完了しただけでは処理を終了しない。`COMPLETED`後はGitHubを再取得し、次の限定遷移を自動開始する。これにより1回の遷移ごとの変更安全性を維持しながら、人間がコマンドを繰り返し起動する必要をなくす。

`python -m tools.loop_engine --once`は診断用の1遷移実行として維持する。

継続実行中は、機械的に解決可能な現在HEADのCI待機状態だけを粗い上限付き間隔で待機し、自動で再取得してよい。レビュー、人間確認（Human Verification）、認証情報、外部提供元（provider）などの外部条件を高頻度に監視してよいという意味ではない。独立して進められる作業（Work）がない場合、これらは型付きの`YIELD_EXTERNAL`として現在の実行を終了する。

Codex実行には固定の経過時間上限による強制終了を設けない。長時間でも生存しているCodex子プロセスは現在の限定遷移へ接続したままにし、実行中は生存通知（heartbeat）を出す。処理時間そのものは失敗証拠ではないため、旧30分強制終了境界は禁止する。明示的なプロセス失敗、起動失敗、`SIGINT`などの決定論的な失敗は引き続き安全側停止（fail-closed）とする。

`python -m tools.loop_engine --validate-installation`は変更を行わない導入確認経路である。CLIは秘密情報を含まない遷移進捗を標準エラー出力へ、構造化した遷移結果を標準出力へ出す。

## 接続口と実行境界

決定論的Coreは`MissionSupervisor`、型付きスナップショット、再開・書込み判定（Resume / Write gate）、注入された実行器・検証器・Checkpoint接続口を保持する。Repositoryはこれらの制御概念を`gh`、Codex、Repositoryルートへ接続するai-liver-yura用ホスト構成も提供し、Loop Engineeringを`app/**`へ混在させない。

ホスト構成は最新の#450 Mission Checkpointを探索候補としてのみ扱う。古い解析可能なCheckpointへ遡らない。最新Checkpointは`current Work`を明示し、PRに紐づくWorkなら`current PR`と厳密なHEADも記録する。現在対象の識別情報が欠落または不正な場合は安全側停止とし、Codex起動やGitHub変更へ進まない。

計画専用Codexの出力も機械可読契約の一部である。選択した次WorkのCheckpointには固定項目`- current Work: #<issue>`を必須とする。有効なPRがある場合は`- current PR: #<pr>`と`- exact HEAD: <40-hex-sha>`も必須とする。`選択した次Work:`などの別名で代用しない。有効なPRがないWorkではPRやHEADを捏造せず省略する。

安全に分類可能な観測失敗は、曖昧な状態へ潰さず型付き原因を表示する。特に不正な最新Checkpointは`GITHUB_OBSERVE_FAILED:MISSION_CHECKPOINT_TARGET_UNRESOLVED`として表示する。認証情報、通信、無効JSON、GitHub応答形状の不整合も秘密情報を出さずに個別分類する。

Codex起動、CI判定、Ready化、統合（merge）、Issue終了、Checkpointの前に、ホストは現在のIssue、PR、branch、HEADを再取得し、古いCheckpoint対象を拒否する。会話記憶を実行上の正本（Authority）として扱わない。

`CodexExecutor`は固定引数列と秘密情報を除外した子プロセス環境を使用する。レビューワー認証情報やデータベース認証情報を渡さず、`TaskPacket`やMission指示をシェル文字列展開せず、Repositoryルートから実行する。1回の限定遷移で起動できるCodex子プロセスは1つだけとする。

## CodexとGit操作の責務境界

実ホストの実装処理ではbranch作成、commit、pushなどGit管理情報の変更が必要になる。一方、Codexは既定で`workspace-write`の隔離領域を使用し、`.git`へ直接書き込ませない。

```text
codex -a never exec --sandbox workspace-write -c sandbox_workspace_write.network_access=true <instruction>
```

Codexは作業ファイルの編集と必要な検証を担当する。branch作成・切替、基幹統合、`git add`、commit、push、PR作成、Checkpoint更新などGit管理情報とGitHub変更は信頼済みホストが担当する。Codexへ`danger-full-access`を与えてGit操作を成立させる方式は採用しない。

Codex子プロセスにはレビューワー認証情報、データベース認証情報、不要な秘密情報を渡さない。信頼済みホスト側のGit/GitHub操作も必要最小限の環境変数だけを引き継ぐ。

Codexプロセスが終了コード0でも、それだけでは実行対象が前進した証拠にならない。実装、CI不具合修正、統合競合解消の後は信頼済みホストがGitHubの現在状態を再取得し、Checkpointの識別情報とPR/HEADが実際に前進したことを確認する。進捗がなければ`IMPLEMENTER_NO_PROGRESS`として安全側停止にする。

## #471の試験対象選択

#471はLoop Engineeringの基盤統合状態を保持するIssueであり、実製品試験そのものではない。

#477統合後に`current Work: #471`かつ有効なPRなしとなった場合、通常実装の続行へ送ってはならない。ホストはこの状態を試験対象選択専用状態として扱い、#471を完了済みWorkとして計画専用Codexを起動する。

計画器は#462/#471自身とLoop Engineering基盤Issueを除外し、GitHubの現在状態とProject #7から依存関係を満たした実製品V2 Workを1件選択する。

計画後は最新Mission Checkpointを再取得する。

- 別の製品Workへ`current Work`が移動した場合は`PILOT_PLANNING_DISPATCHED`として次遷移へ進む。
- Checkpointは更新されたが`current Work`が#471のままなら`PILOT_DEPENDENCY_WAIT`として外部待機へ移る。
- Checkpointが更新されなければ`PILOT_PLANNING_NO_PROGRESS`として安全側停止にする。

## ホスト工程の振り分け

#450から探索し現在状態を再取得した`current Work`について、次のように処理する。

- 現在の実装PRがない通常Work、または実装・CI不具合修正が必要な場合はCodexを1回起動し、その後GitHubを再取得して観測結果をCheckpointへ記録する。
- 厳密な現在HEADのCIがない、または`queued`/`in_progress`なら限定遷移は`YIELD_EXTERNAL`とする。継続実行CLIは操作者の介入なしで待機し、現在HEADのCIを再確認してよい。
- 厳密な現在HEADのCIが失敗なら同一作業系列の機能不具合修正としてCodexを1回起動する。
- 厳密な現在HEADのCIが`PASS`し、既知の再現可能な機能停止要因がなければ、必要に応じてReady化し、期待HEADを固定した通常統合、統合後の基幹再確認、Work完了へ進む。
- 古いCI、HEAD、Checkpoint識別情報は再調整が必要なため安全側停止にする。
- レビュー結果`REQUEST_CHANGES`や`NOT_RUN`だけでは、現在のMission方針上、機能経路を停止しない。

Work統合後は、次の限定遷移でCodexを計画専用として1回起動し、#207/#317/#450/#462とProject #7を再取得して、次の依存関係を満たしたWorkを選択してよい。この計画遷移では製品コードや制御コードを変更せず、統合も行わない。Checkpointには次遷移用の`current Work`、PR、HEADを明示する。

## 継続実行の規則

- `COMPLETED`なら直ちに再観測し、次の限定遷移へ進む。
- `YIELD_EXTERNAL / CI_PENDING`なら継続実行では粗い間隔で待機し、再観測する。待機中は変更しない。
- その他の`YIELD_EXTERNAL`は、スケジューラが別の依存関係を満たしたWorkをすでに選択していない限り安全に処理を終了する。
- `INTERVENTION_REQUIRED`は型付き理由とログパスを残して安全側停止する。
- Mission完了はRoot #317の完了証拠が正本の完了契約を満たした場合だけ正常終了する。
- `--once`は上記に関係なく1回の限定遷移で戻る。

継続実行するホストであっても、同一HEADのレビュー高頻度監視は禁止する。レビュー待ち、人間確認、認証情報、外部提供元の復旧などの外部待機は、高頻度監視禁止規則を維持する。

## 遷移規則

- 再開競合（Resume conflict）では実装用`TaskPacket`を生成せず、変更しない。
- CI証拠は待機・成功・失敗を判定する前に期待する現在HEADへ結び付ける。現在HEADのCIが待機中・実行中なら外部待機へ移り、失敗なら同一作業系列の修正遷移へ戻す。
- 独立レビューは診断情報である。決定論的かつ再現可能な機能停止要因だけが修正を強制し、レビュー提供元の失敗や非機能的な強化要求では統合を止めない。
- 変更は「現在条件の再確認 → 効果の実行 → 効果の再確認 → Checkpoint」の順で行う。正本基幹への直接実装書込みとProject #6変更は拒否する。
- 「実装完了 → 現在HEAD再確認 → 厳密HEAD検証」を1つの識別連鎖として扱う。プロセス終了コード、古いCI結果、別SHAの検証結果だけで遷移を前進させない。
- `SIGINT`では新しい変更を受け付けず、既存の安全終了境界で現在の子プロセスを終了し、次回実行で再調整できるGitHub状態を残す。

## CLI終了コード

`--once`では、`0`は安全な遷移完了、`2`は`YIELD_EXTERNAL`、`3`は安全側停止を要する介入・再調整を意味する。

既定の継続実行では途中の完了遷移で処理を終了しない。自動再開できない外部待機、介入、またはMission完了に達した時だけ最終終了する。終了コードだけで外部API応答を実効果の真実へ格上げしない。
