# 配信信号から注意への変換

所有者: #333。信号生成の所有者: #347。関連: #352、#360。
正本は`attention_turn_contracts.md`第4.2節と訂正文書第3.2節である。

## 公開契約と依存方向

`StreamingCommentSignal`を`app.domain.contracts.streaming`に置く。型のフィールド・検査は維持し、既存の`app.subsystems.streaming.contracts`からも同じ型を再公開する。注意の変換処理はこの共有契約だけを読み、配信実行基盤を読み込まない。配信実行基盤から注意処理への依存も追加しない。

`StreamingAttentionProjector`は`app.usecases.attention`が所有する。起動側の接続処理が、配信実行基盤の`drain_comment_signals`で取り出した集約済み信号を、現在の文脈版を付けた`AttentionProjectionEnvelope`として渡す。コメント全件を直接投入せず、意味理解や返信判断をこの変換処理で行わない。

## 一回限りの信号

一回の取り出しで確定した`signal_id`を注意源の`source_ref`として使い、`STREAMING / OFFER`へ変換する。`source_channel_ref`を長寿命の注意源として使わない。取り出し前の集約中に同じ信号の件数が変わる段階は変換対象ではない。

後続更新のない一意な事実は版を持たなくてよい、という訂正文書第3.2節に従い、この変換では`source_revision`や`expected_source_revision`を生成しない。同じ信号の再投入や容量・文脈版の不適合は既存の注意受付が判断する。長寿命の配信セッションの更新・解消は別の所有事実と版契約が必要であり、この接続で代用しない。

| 注意入力 | 集約済み信号との対応 |
| --- | --- |
| signal_id | attention-signal-を付けた元のsignal_id |
| source_ref | 元のsignal_id |
| source_kind / operation | STREAMING / OFFER |
| source_context_revision | 起動側から渡された現在の文脈版 |
| occurred_at | 集約信号のgenerated_at |
| requested_priority | 未指定。注意方針の既定値を使う |
| trusted_direct_user | false |

コメント数を根拠に優先順位を自己昇格させない。注意状態の確定、処理開始の選択、発話や返答の判断は既存の所有者へ委ねる。

## 検証範囲

模擬の配信入力を本番の集約・変換・注意受付へ通し、種別と優先順位、再投入、容量上限、代表信号の引継ぎを確認する。配信実装の読み込みを禁止しても変換処理を読み込めること、旧公開場所と共有契約が同じ型であることも確認する。

元コメントの本文を参照する仕組み、自然文の意味解析、実配信、長寿命の監視状態の更新・解消を、この変換だけで完成したとは扱わない。
