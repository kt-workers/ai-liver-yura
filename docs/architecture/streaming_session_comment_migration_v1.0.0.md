# Streaming Session／Comment移行監査 v1.0.0

## 1. 結論

工程Hで、Session、Preparation、Readiness、Start／End、Lifecycle、Run of Show、
Opening／Main／Closing、Live Chat polling、Ranking、Moderation、配信固有Response履歴を
`subsystems/streaming`へ移した。正規の状態とロジックはSubsystemが所有する。
旧pathはI〜Jの呼出元を壊さない一段re-export／composition互換に縮小し、Kで削除する。

依存方向は次に固定する。

```text
旧Core互換path -> subsystems.streaming
subsystems.streaming -X-> 旧Plugin / Core Runtime / AgentEvent / ActivityTurnResult
```

## 2. ファイル監査

| 移動前 | 正規path | 責務／依存先 | 互換path | 削除 |
| --- | --- | --- | --- | --- |
| `app/plugins/youtube_streaming/domain/{session,preparation,readiness,start,end,lifecycle}.py` | `subsystems/streaming/domain/` | Session aggregate、version、遷移、readiness。標準ライブラリとSubsystem domainのみ | 一段re-export。I〜JのAdmin／Runtime用 | K |
| `app/plugins/youtube_streaming/domain/{run_of_show,opening,main_segment}.py` | `subsystems/streaming/domain/` | segment定義と配信Activity状態 | 同上 | K |
| `app/plugins/youtube_streaming/domain/{live_chat,comment_moderation,comment_ranking,comment_response}.py` | `subsystems/streaming/domain/` | 正規化、候補、判定、履歴 | 同上 | K |
| `app/plugins/youtube_streaming/application/{prepare_session,start_session,end_session,lifecycle_gate}.py` | `subsystems/streaming/application/` | Session application。Subsystem Portのみ | 一段re-export | K |
| `app/plugins/youtube_streaming/application/{opening,main_segment}.py` | `subsystems/streaming/application/` | Run of Show execution coordination | 一段re-export | K |
| `app/plugins/youtube_streaming/application/{live_chat_poller,comment_moderation,comment_ranking,comment_response}.py` | `subsystems/streaming/application/` | polling、dedup、backpressure、候補選定 | 一段re-export | K |
| `app/ports/{streaming_preparation,streaming_control,youtube_live_chat,youtube_errors,comment_*}.py` | `subsystems/streaming/ports/` | SDK非依存Port／DTO | 一段re-export | K |
| `app/adapters/streaming/in_memory_*`、`preparation_publisher.py`、`yaml_run_of_show_repository.py` | `subsystems/streaming/adapters/repositories/` | immutable Domainの永続化、command cache | 一段re-export | K |

## 3. 境界

- `StreamingSessionComponents`をSubsystem composition rootで構築し、Session repository、
  usecase、lifecycle gate、Run of Show、Comment pipelineを同じ整合性境界に置く。
- YouTube／OBSはG1／G2の正規bundleを利用する。SDK型やraw responseはDomainへ渡さない。
- Character、LLM、TTS、Live2D、字幕、表情、最終応答判断はCoreに残す。
- content executionは中立Portで接続し、未接続時は
  `content_execution.not_connected`の`unavailable`結果を返す。
- TTS／Avatar healthはPortとしてのみ参照し、Core objectを保持しない。
- 旧`StreamPreparationRuntime`はI／JまでのAdmin／Core composition facadeであり、
  正規型・Repository・UsecaseはSubsystemを参照する。新規状態ロジックを追加しない。

## 4. Comment公開Event

Live Chat pollerは内部の正規化Eventに加え、既存`StreamingEventEnvelope`の
`COMMENT_RECEIVED`を発行できる。payloadには正規化済みコメント情報だけを入れ、
`page_token`、`live_chat_id`、OAuth情報、credential、raw Google responseを含めない。
Jまで必要なCore接続は`app.integrations.streaming_comment_compatibility`に置き、
公開Eventから`AgentEvent`への一方向変換だけを提供する。逆変換は提供しない。

## 5. 保持した挙動

- Session遷移、state version、command result cache、retry条件
- Startの承認、外部状態確認、event順序、重複外部操作防止
- normal／emergency End、closing順序、cancel、冪等停止
- Run of Showのopening→main→closing選択
- Live Chatのtoken保持、並べ替え、dedup、優先度、backpressure、backoff
- Moderation reason／stats、Ranking順序／予約、Response履歴／retry

## 6. 後続工程

- I: 完了。Streaming Adminの接続先をSubsystem Admin APIへ変更した。
- J: 完了。Core Streaming Client／Gateway／Event Mapper／Receiverへ置換した。
- K: 完了。旧Plugin、Streaming専用global Port、wrapper、旧bootstrap facadeを物理削除した。
