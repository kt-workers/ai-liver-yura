# 内部指示器クラウド検証モジュール設計 v1.3.5

## 1. 目的

既存7プリセットは、現在の気分、共感、高好奇心、低活性、会話終了、Activity継続、存在境界を検証している。

本版では、内部状態の混同、Knowledge Gap解消、Activity操作の分岐、質問を許可しない境界を追加し、Internal Directive Plannerの判断範囲を比較しやすくする。

## 2. 追加プリセット

### 2.1 怒りが高い状態への直接質問

- `target=internal_state.anger`
- `anger=0.86`
- 直接回答、質問Budget 0、内部数値の非読み上げを確認する

### 2.2 低い喜びと高いEngagement

- `joy=0.08`
- `amusement=0.14`
- `engagement=0.93`
- Engagementを楽しさとして誤解しないことを確認する

### 2.3 既存Knowledge Gapを解消する回答

- 入力発話行為は`answer`
- `information_provided`に既存Gapへの回答を含む
- 対象一致する`related_knowledge.knowledge_gaps`を入力する
- 解消候補を提案しても、回答しただけで関心を低下させないことを確認する

### 2.4 進行中Activityを停止する

- `expected_response=action`
- 進行中Activityあり
- Registryに`stop`と`continue`を登録
- 継続ではなく停止Intentを選択することを確認する

### 2.5 Activityの説明を要求する

- `expected_response=action`
- Registryに`explain`を登録
- 通常回答だけでなく`activity_intent.operation=explain`を選択することを確認する

### 2.6 高い関心だが質問しない

- Curiosity、Engagement、対象別関心は高い
- 対象一致する既知情報はある
- Knowledge Gapは空
- 全体状態と関心だけでは質問を許可しないことを確認する

## 3. 実装

既存完成HTMLを再生成せず、`internal_directive_lab_reviewed.py`で追加プリセット定義を登録する。

- Python側では`compact._PRESETS`へ追加し、テストと検証データで同じ定義を参照する
- ブラウザ側では完成HTMLの末尾へ追加定義を登録するスクリプトを挿入する
- 既存プリセット選択、再適用、GUI同期、API送信、Exportの処理は再利用する

## 4. 互換性

- 既存7プリセットのキーと内容は変更しない
- Render起動先は変更しない
- API契約、Export契約、折りたたみ、Export配置は変更しない
- 追加後のプリセット総数は13件とする

## 5. テスト

- 6件の追加キーがPython定義と完成HTMLの両方へ登録される
- 怒り値がEmotionへ含まれる
- joy／amusementとengagementが別グループに保持される
- Knowledge Gap解消プリセットに既存Gapと回答情報がある
- stop／explainがRegistry操作と一致する
- 高関心・GapなしプリセットでKnowledge Gapが空である
- Exportパネルの既存DOM順序を維持する
