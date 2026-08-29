# Loop環境・利用能力の事前確認

Issue #463はLoop Engineering（#462）の起動前判定を実装する。作業系列を選択する前に実行環境を確認し、GitHub Projectsを変更したりOpenAI要求を開始したりしない。

## 正本と境界

- GitHub Issue、PR、Project #7を現在状態の正本とする。保存済みの項目識別子をこのコマンドの入力にしない。
- このコマンドが確認してよいProjectは#7だけである。Project変更コマンドを実行せず、Project #6を対象にしない。
- Codex/VS Code再起動後を含め、実行のたびにProject #7の3つの読取確認（`view`、`field-list`、`item-list`）をすべて実施する。過去の成功結果を再利用しない。
- レビューワー認証情報、Docker、PostgreSQLの利用能力がない場合はWork単位の利用不可として報告する。Mission全体の停止条件にはしない。
- コマンド出力は真偽の利用能力結果と、安定した秘密情報を含まない診断コードへ縮約する。コマンドの生出力、token値、データベースURL、環境変数値を公開しない。

## 契約

`python -m tools.loop_engine.preflight`はJSONオブジェクトを1つ出力する。

```json
{
  "status": "PASS",
  "capabilities": {"github_repo_read": true},
  "blocking_for_loop_bootstrap": [],
  "work_scoped_unavailable": [],
  "diagnostics": []
}
```

`status`は起動に必須の利用能力がない場合`BLOCKED`、Work単位の利用能力だけがない場合`DEGRADED`、それ以外は`PASS`とする。

## 確認項目

| 利用能力 | 証拠コマンド | 失敗時の分類 |
| --- | --- | --- |
| GitHub Repository読取 | `gh repo view` | 起動停止 |
| GitHub Repository書込 | 固定RepositoryへのREST権限照会（`permissions.push`） | 起動停止 |
| Project #7読取 | `gh project view`、`field-list`、`item-list` | 起動停止 |
| Project #7書込 | GraphQLの読取専用`viewerCanUpdate`照会 | 起動停止 |
| OpenAIレビューワー | 信頼済みホスト仲介器への上限付き健全性要求 | Work単位 |
| PostgreSQLクライアント | `psql --version` | Work単位 |
| PostgreSQLサーバー・DB | `pg_isready`後、秘密情報だけを含む子プロセス環境で`SELECT 1` | Work単位 |
| PostgreSQL移行 | `alembic.ini`が存在する場合だけ`alembic current` | Work単位 |
| 開発道具 | プロジェクトPython/venv、pytest、Ruff、Mypy、compileall、Codex CLI | 起動停止 |

Project書込結果は、毎回取得する副作用のないGitHub権限照会である。注入された試験用フラグ、保存済み項目ID、変更操作ではない。#462/#463で制御して実施したProject #7変更は独立した履歴証拠として保持する。

Repository書込結果も、`ktan514/ai-liver-yura`へ固定した副作用のない照会を毎回実施する。事前確認は認証済み利用者の当該Repositoryに対する`permissions.push`だけを読む。`git push --dry-run`、現在remote、upstream、forkを証拠として使用しない。権限結果が欠落、不正、またはfalseの場合は安全側停止にする。

## 厳密HEAD CIの識別

`workflow_dispatch`は`pr_number`と`expected_head_sha`を受け取る。識別処理は番号から現在PRを読み、現在HEADが明示された期待SHAと一致すること、基点refが`rebuild/v2-foundation`であることを要求し、解決した現在HEAD/基点SHAを出力する。`github.sha`をPR HEADの証拠として使用しない。`pull_request`の場合は、解決値がイベントのHEAD/基点とも一致する必要がある。checkout、厳密HEAD検証、差分確認は解決済み出力だけを使用する。並行実行キーはどちらのイベントでもPR番号を基準にする。

`LOOP_DATABASE_URL`は子プロセス確認用の`PG*`変数を導出するためだけに使用し、コマンド引数、結果、診断へ含めない。#463が検証するのは、移行設定が存在する場合の移行**利用能力**である。Loop運用記憶の表を作成したり移行を適用したりしない。それらは#462配下の後続運用記憶実装が担当する。

## 再起動確認

#463完了前に、Codex環境から供給される認証情報注入だけを持つ新しい最小プロセスを起動し、GitHubとProject #7の読取確認を実施する。`gh auth login`、`gh auth refresh`、対話操作なしで成功しなければならない。これは新しいプロセスへの認証情報注入を確認するものであり、Projectを変更しない。

## macOSホスト起動器

Repositoryホストから`python scripts/launch-codex-v2.py`を実行する。起動器は`.env`を直接読まない。承認済みのホスト側環境読込器が起動前に`GH_TOKEN`を注入し、起動器はGitHub/VS Code子プロセス環境だけへ渡す。Goalの版・世代・SHA-256は正本ファイルから導出し、Homebrew用のPATHを維持してVS Codeを起動する。認証情報は表示も保存もしない。VS Codeが新しいCodexプロセスを作成した後、通常の事前確認を実施する。手動`export`、`gh auth login`、`gh auth refresh`は運用経路に含めない。

## 信頼済みホストの独立レビューワー

任意の正本レビューは通常の事前確認から意図的に分離する。完全な正本境界は[信頼済みホストレビューワー境界](../architecture/v2/trusted_host_reviewer_boundary.md)に定義する。

対象作業領域はレビューワークライアントを取り込まず、`OPENAI_API_KEY_REVIEWER`も受け取らない。秘密情報を含まない`YURA_TRUSTED_REVIEWER_SOCKET`だけを受け取ってよく、事前確認はこの経路で上限付き健全性要求を行う。すべての対象作業領域の外側にある信頼済みホスト仲介器が、認証情報検証、モデル照会、上限付きResponses API健全性確認、現在PR識別・差分取得、レビュー呼出、結果検証を所有する。仲介器は厳密HEADを独立して結び付けて再確認し、対象が古ければ`NOT_RUN`を返し、GitHub書込権限やデータベース認証情報をレビューワーへ渡さない。

起動器はGitHub/VS Code用にホスト注入済み`GH_TOKEN`だけを使用する。`.env`を読まず、レビューワー認証情報を取得せず、レビューワーコードを起動しない。
