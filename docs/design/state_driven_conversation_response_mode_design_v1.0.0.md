# 状態駆動会話応答モード設計 v1.0.0

## 1. 背景

実プロセスログから、次の二つの問題が確認された。

1. 挨拶や短い相槌に対し、Character LLMが質問、新話題、自己開示、意味的復唱を追加する
2. これを抑えるために追加した固定的な発話制約が、Drive・Desire・Motivationによる主体的な質問や発話まで禁止し得る

旧方式では、次のような入力・対話分類を直接の禁止条件として使用していた。

```text
低主体性
→ 質問禁止
→ 新話題禁止

短い相槌
→ 質問禁止
→ 自己開示禁止
→ 話題展開禁止
```

この方式は症状を抑制できる一方、同じ相槌入力でも好奇心が強い場合、関係性を深めたい場合、表現欲が高い場合などの内的差異を失う。

## 2. 目的

Character LLMへ渡す直前に、今回どのように会話へ関わるかを状態から選ぶ。

```text
answer
ask
listen
react
speak
observe
```

入力分類は判断材料として使用するが、質問・発話を一律禁止する条件にはしない。

## 3. 責務境界

本設計はCharacter発話の関わり方を選ぶ層である。

変更するもの:

- Character Promptへ渡す実効Response Content Plan
- question_budget
- new_direction_budget
- self_disclosure_level
- conversation_strategies
- Character LLMとValidatorが共有する応答モード

変更しないもの:

- Situation Evaluatorが決めたActivity
- Activityの実行可否
- 権限・安全判定
- Emotion／Drive／Desireの更新式
- MoralによるActivity候補限定適用
- 接触対象・接触部位・ドラッグ区間

## 4. 入力

応答モード選択では次を使用する。

### 4.1 内的状態

- `drive.curiosity`
- `drive.engagement`
- `drive.boredom`
- `drive.energy`
- `response_content_plan.primary_desire`
- `response_content_plan.conversation_strategies`
- `response_content_plan.question_budget`
- `response_content_plan.new_direction_budget`

Response Content PlanはDesire・Motivation・Moralから導出済みであるため、これを通じて欲望、対人姿勢、抑制、価値強調を参照する。

### 4.2 会話状況

- `speech_act`
- `conversation_phase`
- `initiative_level`
- ユーザー入力の情報量
- 挨拶かどうか
- 短い相槌・同意かどうか

## 5. 選択方式

各応答モードへスコアを与え、最高得点のモードを選ぶ。

### 5.1 `ask`

上昇要因:

- curiosityが高い
- primary_desireが`curiosity`
- `ask_follow_up`、`ask_for_detail`、`seek_clarification`
- question_budgetが1
- engagementが高い
- boredomが高く、話題を探索したい

低下要因:

- initiative_levelが低い
- greeting
- 短い相槌
- primary_desireが`security`

相槌や挨拶による低下は減点であり禁止ではない。十分に強い好奇心があれば`ask`を選択できる。

### 5.2 `listen`

上昇要因:

- 短い相槌・同意
- engagementが高い
- primary_desireが`connection`
- `acknowledge_other`
- `observe_before_speaking`
- `slow_down`

### 5.3 `react`

上昇要因:

- greeting
- engagementが高い
- primary_desireが`expression`
- `share_reaction`
- `state_preference`

### 5.4 `speak`

上昇要因:

- boredomが高い
- energyが高い
- primary_desireが`autonomy`、`achievement`、`recognition`
- 新方向Budgetがある
- `take_initiative`
- `state_choice`
- `define_next_step`
- `self_disclose_briefly`

initiative_levelが低くても、これらが十分に強ければ`speak`を選択できる。

### 5.5 `observe`

上昇要因:

- energyが低い
- primary_desireが`security`
- `observe_before_speaking`
- `slow_down`

### 5.6 `answer`

ユーザーの確定済み`speech_act`が`question`の場合は、質問へ直接答える責務を優先する。

これは入力分類による会話展開禁止ではなく、ユーザーが求めた回答を別の質問や話題で回避しないための応答義務である。

## 6. 実効Response Content Plan

選択したModeに合わせて、元のResponse Content PlanからCharacter用の実効Planを作る。

### answer

- 質問へ直接答える
- question_budget=0
- new_direction_budget=0
- 根拠のない自己開示を行わない

### ask

- 質問戦略を1件以上保持
- question_budget=1
- new_direction_budget=0
- 質問前の長い復唱を行わない

### listen

- `acknowledge_other`等を使用
- question_budget=0
- new_direction_budget=0
- self_disclosure_level=none

### react

- `share_reaction`等を使用
- question_budget=0
- new_direction_budget=0
- 原則短い感情反応

### speak

- 元の発話・提案・自己表現戦略を保持
- 元のquestion_budgetとnew_direction_budgetを維持
- 一つの考えや方向へ絞る

### observe

- `observe_before_speaking`等を使用
- question_budget=0
- new_direction_budget=0
- 最小限の発話・表情・間に留める

## 7. Character LLMとValidatorの整合

旧実装ではCharacter Promptだけが縮退後Planを知り、Validatorは元のResponse Contextとinitiative_levelを見ていた。

そのため、Characterが生成した質問をValidatorが拒否し、再生成が発生する可能性があった。

新実装ではCharacter LLMとValidatorが同じ関数を呼び、次を共有する。

```text
Conversation Response Decision
Effective Response Content Plan
```

これにより、初回生成と検証の契約を一致させる。

## 8. Trace・観測

`ConversationResponseDecision.as_context()`は次を出力する。

- mode
- confidence
- 各Modeのscore
- reasons
- low_information_input

現段階ではPromptへ含める。後続でTraceLoggerへ専用イベントとして記録できる。

## 9. 回帰条件

次をテストで固定する。

1. 通常の短い相槌では`listen`を選ぶ
2. 短い相槌でも好奇心が十分高ければ`ask`を選べる
3. 低主体性の挨拶では通常`react`を選ぶ
4. 低主体性でも強いautonomy・boredom・energyにより`speak`を選べる
5. 直接質問では`answer`を選ぶ
6. Character PromptへDecisionを投影する
7. Validatorが同一Decisionと実効Planを使用する
8. 旧固定文言をPromptへ残さない

## 10. 実動作確認

同一プロセスで次を確認する。

### 通常状態

```text
人間: こんにちは
期待: 短い返礼または反応
```

```text
人間: いいね。そういうの
期待: 短い受け止め
```

### 高好奇心状態

```text
人間: いいね。そういうの
期待: 状態がaskを選んだ場合のみ、自然な質問を1件行う
```

### 直接質問

```text
人間: 今日は何がしたい？
期待: 最初に明確な選好・回答を示す
```

確認項目:

- Character初回生成とValidator判定が一致する
- 不要な再生成が発生しない
- 相槌への意味的復唱が減る
- 状態が強いときの質問・発話が失われない
- `Conversation Response Decision`のmodeと最終発話が一致する

## 11. 後続課題

本設計はCharacter発話内の関わり方を選ぶ層である。

次は別工程で扱う。

- `listen`や`observe`を無音・非言語Actionとして実行できる出力契約
- EmotionをModeスコアへ直接使用する設計
- Relationshipによる質問距離・自己開示量の調整
- 過去数ターンの質問頻度・話題反復を考慮した抑制
- Mode決定をRuntime Traceと管理画面へ表示
- Mode選択をLLMへ任せる場合の責務境界と決定論的Fallback
