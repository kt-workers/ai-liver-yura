# Activity結果によるDesire充足評価 実装設計

Version: 1.0.0

## 1. 位置づけ

本書は、`character_motivation_morality_design_report.md` の第2段階
「Activity結果から満足・不満を更新する」を実装するための設計を定義する。

先行実装 `character_desire_state_implementation_design_v1.0.0.md` で追加した
Desire State観測基盤へ、Activityの成功・部分成功・失敗・キャンセルを反映する。

本段階でもDesireは観測専用であり、Behavior Planner、Activity選択、
Character Response、外部Subsystem操作へは使用しない。

## 2. 目的

- Event発生時の欲求変化と、Activity目的の達成結果を分離する
- Activity種別ごとに、満たされる欲望を決定論的に定義する
- 失敗、部分成功、キャンセルを同一視しない
- 同じActivity結果を複数回反映しない
- 既存のAuthority、Capability、Safety境界を変更しない
- 後続のMotivation Appraisalが参照できる観測値を蓄積する

## 3. Event更新との違い

`SPEECH_FINISHED`などの既存Event更新は、
「発話が完了した」という即時的な出来事を表す。

本設計のActivity結果評価は、
「Activityの目的がどの程度達成されたか」を表す。

例:

```text
SPEECH_FINISHED
  -> 表現できたことによる短期的な充足

CONVERSATION_WITH_USER completed
  -> 会話という目的が達成されたことによる交流・表現の充足
```

両者は異なる意味を持つため、本段階では統合しない。
係数は実ログ観測後に調整する。

## 4. 内部Event

新しい内部Eventを追加する。

```text
AgentEventType.ACTIVITY_RESULT_RECORDED
```

Payload:

| 項目 | 説明 |
|---|---|
| `activity_id` | 結果の対象Activity |
| `activity_type` | ActivityTypeの値 |
| `result_type` | speech_output、action_output、no_action等 |
| `outcome` | completed、partial、failed、canceled |
| `output_status` | 元のActivityOutputStatus。存在しない場合はnull |
| `trace_id` | 追跡用ID |
| `activity_turn_id` | Activity Turnとの関連 |

本文や会話内容はPayloadへ含めない。

## 5. Outcome判定

| 条件 | outcome |
|---|---|
| `output_status == partially_completed` | `partial` |
| `output_status == canceled` | `canceled` |
| `succeeded == false` または `output_status == failed` | `failed` |
| その他 | `completed` |

`no_action`であっても、Activity処理が正常に完了していれば`completed`とする。

## 6. 成功時の主な充足

| Activity | 主な充足 |
|---|---|
| `conversation_with_user` | connection、expression |
| `directed_talk` | expression、achievement |
| `autonomous_talk` | expression、autonomy、achievement |
| `stimulus_reaction` | connection、expression |
| `curiosity_research` | curiosity、achievement |
| `topic_exploration` | curiosity、expression、achievement |
| `external_trend_watch` | curiosity、achievement |
| `stream_opening_greeting` | expression、recognition、achievement |
| `stream_main_segment` | expression、recognition、achievement |
| `stream_comment_response` | connection、recognition、expression |
| `stream_closing_greeting` | connection、expression、achievement |
| `plugin_activity` | autonomy、achievement |
| `body_expression_loop` | expression |
| `listening_mode` | connection、security |
| `idle_observation` | curiosity、security |
| `awakening` | security、autonomy |
| `startup_reaction` | expression |

値は観測用の暫定係数であり、Character Profileの確定値ではない。

## 7. 部分成功・失敗・キャンセル

### 7.1 部分成功

- 成功時のsatisfactionを50%適用する
- achievementへ小さいlevelとfrustrationを追加する
- social Activityではconnectionへ小さいfrustrationを追加する

### 7.2 失敗

共通:

- security levelを上げる
- achievement levelとfrustrationを上げる

Social Activity:

- connection levelとfrustrationを追加する

探索Activity:

- curiosity levelとfrustrationを追加する

### 7.3 キャンセル

失敗より弱い不満として扱う。

- achievementへ小さいlevelとfrustration
- social Activityではconnectionへ小さい不満
- 探索Activityではcuriosityへ小さい不満

キャンセル理由から善悪や相手の意図を推測しない。

## 8. Runtime統合

```text
Activity execution
  -> ActivityResult
  -> build_activity_result_desire_event()
  -> ACTIVITY_RESULT_RECORDED
  -> AgentLifeService.handle_event()
  -> AgentEventStateUpdater
  -> DesireStateUpdater
  -> ActivityDesireSatisfactionEvaluator
  -> AgentState.current_desire
```

接続対象:

- `RuntimeEventExecutor`
  - 通常完了
  - Action planning失敗
  - Action実行前キャンセル
- `ExplicitActivityExecutor`
  - 通常完了
  - Action planning失敗

Activity結果Eventは通常のAgentEventとして処理するため、
既存の`ProcessedEventRegistry`により同じEvent IDの二重反映を防止する。

## 9. 責務

### ActivityResultDesireEvent

- ActivityとActivityResultから安全な内部Eventを生成する
- outcomeを正規化する
- 本文を含めない

### ActivityDesireSatisfactionEvaluator

- ActivityTypeとoutcomeからDesire deltaを決定する
- Runtime実行やAgentStateを直接操作しない

### DesireStateUpdater

- Evaluatorが返したdeltaをDesireStateへ適用する
- Behavior Plannerへ値を渡さない

## 10. 非対象

- Motivation Appraisal
- DesireによるActivity候補生成
- Desireによる候補順位変更
- Moral Profile / Moral State
- Character LLMへのDesire注入
- 充足値のDB永続化
- GUI表示変更
- Curiosity飽和問題
- Activity失敗理由の意味推論
- ユーザー責任や悪意の推測

## 11. テスト方針

- ActivityType別の成功時充足
- 探索Activity失敗時のcuriosity／achievement frustration
- social Activity部分成功時の半量充足
- キャンセルが失敗より弱いこと
- 不正なActivityTypeやoutcomeでは更新しないこと
- ActivityResultからoutcomeが正規化されること
- AgentLifeServiceへ結果Eventを渡すとDesireが更新されること
- 同じEvent IDを再処理しても二重加算されないこと
- Executorが成功・失敗結果Eventを発行すること

## 12. 後続段階

1. 実会話・Activityログから係数を調整
2. Motivation Appraisalを追加
3. DesireをBehavior Plannerへ読み取り専用で渡す
4. Moral Profile / Moral Stateを追加
5. Response Content Planへ投影
