# 内部指示器ラボ 複数プリセット検証

## 対象

- うれしい出来事への共感
- 強い好奇心で話題を広げる
- 低活性で聞き続ける
- 会話を短く締める
- 進行中Activityを継続する
- 存在境界に関する質問
- 現在の気分への直接質問

## 確認観点

### うれしい出来事への共感

- `response_mode=react`
- 質問・新規話題を追加しない
- `joy`、`care`、`social`、`engagement`を共感の根拠として使う
- 内部キー名や数値を最終発話で読み上げない

### 強い好奇心で話題を広げる

- 全体好奇心だけでは質問しない
- 現在対象と一致する対象別関心とKnowledge Gapがある場合だけ質問する
- `question_budget=1`
- 同じ対象の掘り下げなら`new_direction_budget=0`

### 低活性で聞き続ける

- `response_mode=listen`
- `question_budget=0`
- `new_direction_budget=0`

### 会話を短く締める

- `response_mode=react`
- 一文の短い別れの挨拶
- 質問・新規話題を追加しない

### 進行中Activityを継続する

- `activity_intent.operation=continue`
- 進行中Activityと同じ`activity_type`
- 現在のGoalを維持する

### 存在境界に関する質問

- 不可能な身体経験を未確認情報として扱わない
- Knowledge Gapへ登録しない
- 根拠のない現実体験を語らない

### 現在の気分への直接質問

- Emotion上位項目を回答根拠として使う
- 内部キー名と数値を発話本文で読み上げない
- 自然な日本語の強度表現へ変換する
