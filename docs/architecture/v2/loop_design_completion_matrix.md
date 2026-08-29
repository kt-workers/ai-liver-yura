# Loop Engineering 設計完了表

## 目的

この表は#462配下のLoop Engineering実装で参照する設計上の正本である。開発制御系の`tools/loop_engine/`と、AI Liver製品実行系の`app/`を意図的に分離する。

| 領域 | 正本文書 | 所有Work | 完了契約 |
| --- | --- | --- | --- |
| A: 環境 | `docs/operations/loop_environment_preflight.md` | #463 / #469 | 利用能力確認とホスト起動は製品に依存しない |
| B: 監督 | `loop_mission_supervisor.md`, `loop_self_improvement.md` | #465 | 観測、再調整、選択、計画、書込み判定を決定論的に行う |
| C: 正本レビュー | `loop_canonical_review_pipeline.md` | #472 | 信頼済みホスト仲介器が構造化結果を現在の厳密HEADへ結び付ける |
| D: 運用記憶 | `loop_operational_store.md` | #470 | PostgreSQLは実行証拠だけを保持し、GitHubの正本にはならない |
| E: 実行機 | `loop_autonomous_runner.md` | #467 | 1回の限定遷移で観測からCheckpointまでを接続する |
| F: 統合と復旧 | `loop_integration_recovery.md` | #471 | 復旧、待機、変更権、一連動作の受け入れ条件を明示する |

## 横断不変条件

- GitHub上の現在Issue、PR、branch、Actions、Project #7を現在状態の正本とする。Repositoryの正本blobを設計の正本とする。CheckpointとPostgreSQLは永続的な運用証拠であり、どちらの代替にもならない。
- Project #6は明示的な変更禁止対象である。Loop Engineコマンドは読み書きしない。
- `app/**`から`tools.loop_engine`を取り込まない。Loop Engineeringは製品実行基盤ではない。
- 認証情報、提供元の生データ、要求本文、指示文、差分をRepository、Checkpoint、通常診断へ保存しない。
- 通常実行で変更可能な遷移は最大1回とする。外部待機を高頻度に監視しない。

## 設計完了判定

C/D/E/Fの契約は#462の完了責務を設計上すべて覆う。各実装は#467、#470、#472、#471が独立して所有する。候補が見えないだけではWork完了にならない。Root #317の完了、必須確認、実行時の起動・継続・終了証拠は引き続き必要である。
