# 入力意味・内部司令 Runtime Guard設計 v1.0.6

## 1. 目的

内部指示器ラボで複数プリセットをまとめて実行した結果、次の改善点を確認した。

- ユーザーのうれしい出来事の共有で、共感的な`react`ではなく受領中心の`listen`が選ばれる
- 強い全体好奇心だけを理由に質問しない制約は正しいが、対象別Knowledge Gapを持つ入力を検証できるプリセットになっていない
- closingのPlanner生出力が`listen`となり、短い別れの挨拶が明示されない
- 進行中Activityの明示的な継続要求でも`activity_intent=null`になる
- 身体経験と無関係な入力にも存在境界の禁止事項が機械的に列挙される

本設計では、Planner PromptとCore Validatorの両方を改善し、クラウド検証ラボの停止位置がPlannerであっても自然な候補を確認でき、完全Runtimeでも同じ上限が保証されるようにする。

## 2. 肯定的体験への共感

次を肯定的体験への共感入力として扱う。

- `expected_response=acknowledgement`
- `primary_intent`または対象が肯定的なユーザー体験を示す

この場合は次を適用する。

- `response_mode=react`
- `question_budget=0`
- `new_direction_budget=0`
- `joy`、`care`、`social`、`engagement`を共感反応の内部根拠として使う
- 単なる受領で終わらず、短く一緒に喜ぶ
- 内部状態のキー名や数値は発話で読み上げず、自然な明るさと共感へ変換する

## 3. 対象別Knowledge Gapによる質問許可

全体的な`drive.curiosity`だけでは質問を許可しない既存方針を維持する。

質問を許可できるのは、現在の入力対象と一致する`related_knowledge`に次が存在する場合とする。

- 対象別関心値が中程度以上
- 具体的な既存Knowledge Gapがある

この場合は次を適用する。

- `response_mode=ask`を許可
- `question_budget=1`
- 同じ対象を掘り下げる質問なら`new_direction_budget=0`
- 既存Knowledge Gapを`new_knowledge_gaps`として作り直さない

Core ValidatorはPlanner候補の`target_interest_updates`だけでなく、入力済み`related_knowledge`も質問許可の根拠として確認する。

## 4. closing

`input_speech_act=closing`では、PlannerとValidatorの双方が次を保証する。

- `response_mode=react`
- 短い別れの挨拶を1文で返す
- `question_budget=0`
- `new_direction_budget=0`
- `expected_response=no_response`でも無言終了にはしない

## 5. 進行中Activityの継続

次の条件をすべて満たす場合は、進行中Activityの継続要求と判断する。

- `expected_response=action`
- `target.type=activity`
- `primary_intent`が継続・再開を示す
- `ongoing_activity`が存在する
- 同じ`activity_type`がAvailable Activityに存在する
- 操作一覧に`continue`がある

この場合は次を適用する。

```json
{
  "activity_type": "<ongoing activity type>",
  "operation": "continue",
  "constraints": {
    "maintain_current_goal": true,
    "source": "ongoing_activity"
  }
}
```

Plannerが`activity_intent=null`を返した場合でも、Core Validatorは上記条件から決定論的に`continue`を復元する。

Activity Registryの操作一覧は、移行期間中の互換性として次の両方を受理する。

- `supported_operations`
- `operations`

## 6. 存在境界の具体化範囲

Character Profileと存在境界は常に有効だが、身体経験と無関係な通常入力へ同じ禁止事項を毎回列挙しない。

具体的な`content_requirements`と`forbidden_claims`を追加するのは、入力意味が次を対象とする場合に限定する。

- 身体状態
- 物理的行動
- 現実空間での実体験

これにより、共感、相づち、closing、Activity継続のInternal Directiveを簡潔に保つ。

## 7. 内部状態の数値と最終発話

Emotion／Drive等のキー名と数値は司令の根拠として保持するが、Character LLMの発話本文へそのまま出さない。

例:

- 内部根拠: `calm=0.74`
- 発話表現: 「かなり落ち着いている」

Core Validatorは、内部表現を自然な日本語へ変換する要件と、そのまま読み上げない禁止事項を補強する。

## 8. JSON契約と停止境界

- `InternalDirective`のJSON Schemaは変更しない
- クラウド検証ラボの停止位置は`internal_directive_planner`のまま
- Planner生出力では候補選択の改善を確認する
- 完全RuntimeではCore ValidatorがActivity継続、共感、質問許可、closingを補強する

## 9. テスト

次を回帰テストで固定する。

- Planner Promptに共感、closing、対象別Gap、Activity継続、存在境界簡素化の指針が含まれる
- `operations`表記でもActivity継続Intentを受理する
- Plannerが`null`でも明示的な継続要求から`continue`を復元する
- 肯定的体験共有を`react`へ補正する
- 対象別関心と既存Gapがある場合だけ質問を許可する
- 全体好奇心だけでは質問を拒否する
- closingを短い`react`へ補正する
- 内部キー名と数値を最終発話で読み上げない要件を追加する
