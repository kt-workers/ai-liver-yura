# 活動実行から配信操作への接続

所有者: #347。関連: #329、#352、#360。
`streaming_subsystem_contracts.md`第5・6・16節と`activity_execution_contracts.md`第4〜7節を実装へ接続する対応表である。

## 入口と所有

`StreamingActivityExecutionAdapter`は配信側に置き、`ActivityExecutionPort`を実装する。起動側が既存の`StreamingSubsystemRuntime`、明示した操作対応表、時刻取得関数を渡す。活動側の受付・開始直前の再検査を通った`ExecutionDispatchRequest`を受け、配信の実行結果を活動側へ返す。実行結果の確定は引き続き`ActivityExecutionAuthority`が行う。

`StreamingActivityOperationBinding`は能力識別子、活動の操作参照、`StreamingOperation`の対応を保持する。同じ能力と操作参照の重複を禁止する。自然文や表示名を操作へ変換しない。初期の4操作は配信側の設定済み環境を使うため、活動引数は空のオブジェクトとし、外部サービスの識別子や未定義引数を黙って無視しない。

一回の実行は選択済みの一つの能力・版に限る。複数の異なる能力を要求する複合実行をこの接続だけで完了扱いにしない。操作対応がない場合や不正な引数の場合、外部呼出し前の`FAILED`を返し、効果の不確かさは`NONE`とする。

## 要求の対応

| 配信要求 | 活動実行の出典 |
| --- | --- |
| execution_id | dispatch_id |
| activity_id | command_id。既存の活動履歴もこの識別子をsource_idに使用する |
| capability_id / descriptor_revision | 受付で固定されたCapabilityBinding |
| operation | 明示した操作対応表 |
| source_context_revision / goal_revision / attention_revision | command.revisions |
| deadline_at | command.deadline_at |
| trace_id | dispatch_id |

配信側は既存の能力世代・利用可否・期限検査を行う。接続側は活動の受付や現在状態の再検査を省略する別の実行経路を作らない。

## 報告と効果

| 配信報告 | 活動側へ返す報告 |
| --- | --- |
| SUCCEEDED / APPLIED | 同じ能力・版・操作に対応する効果証拠付きAPPLIED、その後COMPLETED |
| FAILED | FAILED |
| PROVIDER_UNAVAILABLE | FAILED |
| UNKNOWN_EFFECT | FAILED |
| CANCELLED | CANCELLED |
| TIMED_OUT | TIMED_OUT |

失敗時は配信の`NOT_APPLIED → NONE`、`AMBIGUOUS → POSSIBLY_APPLIED`、`UNKNOWN → UNKNOWN`をそのまま対応させる。報告の時刻、配信状態値、効果状態、再試行可否、公開診断を保持する。成功時の効果証拠には配信操作と観測参照を含めるが、現在の外部状態が`LIVE`や`ENDED`だとは推定しない。

報告の識別子・操作が要求と一致しない場合は、外部呼出し後の効果不明として`FAILED / UNKNOWN`を返す。期限後に判明した効果は既存の活動確定処理が証拠を残して`TIMED_OUT`へ閉じる。

## 取消と試験

呼出し前に取消信号が立っていれば配信を開始せず、`CANCELLED / NONE`を返す。開始後の強制取消と穏やかな取消の区別は活動実行基盤が所有する。接続は配信側の取消報告を変換し、外部効果を未実行と断定しない。

本番の活動実行基盤と配信実行基盤を接続した試験で、4操作、能力の不一致、未定義引数、開始前後の取消、提供先の失敗、期限後の効果保持を確認する。模擬提供先での結合を実配信や自然文の意味理解の証明としない。
