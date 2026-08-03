# 内部指示器（司令塔LLM）クラウド検証モジュール設計 v1.1.0

## 1. 目的

ブラウザ上の独立した検証環境で `InternalDirectivePlanner` を実行し、司令塔LLMが生成する `InternalDirective` を観察できるようにする。

v1.1.0では、JSONを直接記述しなくても検証条件を構築できるGUI入力を追加する。JSON入力は廃止せず、高度な入力・コピー＆ペースト・障害調査用の代替編集モードとして残す。

## 2. 検証境界

実行する処理は次の1段のみとする。

```text
StructuredInputMeaning
+ Internal State
+ Available Activities
+ Ongoing Activity
+ Character Profile / Existence Boundaries
        ↓
InternalDirectivePromptBuilder
        ↓
InternalDirectivePlanner（司令塔LLM）
        ↓
InternalDirectiveJsonParser
        ↓
停止
```

次の処理は実行しない。

- Input Meaning Interpreter
- Internal Directive Validator
- Capability / Authority / Safetyによる実行可否判定
- Activity実行
- Character LLM
- Response Validator
- TTS、字幕、アバターなどの出力プラグイン

## 3. UIデータモデル

画面内部では次の5セクションを単一のJavaScriptデータモデルとして保持する。

```text
meaning
state
activities
ongoing
profile
```

API送信時は次へ対応付ける。

```text
meaning     -> structured_input_meaning
state       -> internal_state
activities  -> available_activities
ongoing     -> ongoing_activity
profile     -> character_profile
```

GUI入力とJSON入力は別々の状態を持たず、同じデータモデルを編集する。

## 4. 入力モード切替

各セクションのヘッダーに、以下のトグルを設ける。

- GUI入力
- JSON入力

### 4.1 GUIからJSONへ切り替える場合

1. GUIの入力値をデータモデルへ反映する。
2. データモデルを整形済みJSONへ変換する。
3. JSONテキスト欄へ表示する。

### 4.2 JSONからGUIへ切り替える場合

1. JSONをパースする。
2. 正常な場合だけデータモデルを置き換える。
3. GUIを再描画する。
4. JSONが不正な場合はJSONモードを維持し、エラーを表示する。

### 4.3 実行時

GUI表示中のセクションはGUI値を、JSON表示中のセクションはJSONをデータモデルへ反映した後、APIへ送信する。

## 5. StructuredInputMeaning GUI

次の項目をGUI化する。

- `input_speech_act`: 選択ボックス
- `primary_intent`: テキスト入力
- `expected_response`: 選択ボックス
- `conversation_phase_signal`: 選択ボックス
- `confidence`: 0〜1のスライダーと視覚メーター
- `target`: 有無のラジオボタン、種別、ID
- `negated`: ラジオボタン
- `hypothetical`: ラジオボタン
- `past_reference`: ラジオボタン
- `information_provided`: 1行1件のリスト入力
- `entities`: 1行1オブジェクトの簡易 `key=value` 入力
- `references`: 1行1オブジェクトの簡易 `key=value` 入力
- `reason`: テキスト入力

複雑なエンティティや入れ子参照はJSONモードで入力する。

## 6. Internal State GUI

次の5グループを数値状態として扱う。

- emotion
- drive
- relationship
- motivation
- moral

各数値項目には以下を表示する。

- 0〜1のスライダー
- 0〜1の数値入力
- 横方向メーター
- 「とても低い／低い／中程度／高い／とても高い」の強度ラベル
- 項目キー
- 日本語表示名（既知の項目のみ）

各グループには任意キーの追加・削除機能を持たせる。これにより、将来内部状態モデルへ新項目が追加されても検証画面の固定実装を待たず試せる。

### 6.1 状態サマリー

グループごとに以下を表示する。

- グループ内の平均値を円形メーターで表示
- 最も高い項目名と値を表示

これは状態の正確な判定値ではなく、入力内容を目視確認するための補助表示とする。

### 6.2 状況・記憶

以下をフォーム入力可能にする。

- `situation.current_topic`
- `related_knowledge`: 1行1件
- `memory`: 1行 `key=value`
- `last_activity_result`: テキストまたはJSON文字列

複雑なオブジェクトはJSONモードで編集する。

## 7. Available Activities GUI

Activityをカード形式で追加・削除できるようにする。

各カードは以下を持つ。

- `activity_type`
- `description`
- `operations`

既知のoperationはチェックボックスで選択する。

```text
start
continue
stop
explain
discuss
```

未知のoperationはカンマ区切りの追加欄から入力できる。

## 8. Ongoing Activity GUI

進行中Activityの有無をラジオボタンで選択する。

「なし」の場合は `null` を送信する。「あり」の場合は以下を入力する。

- `activity_type`
- `goal`
- `expected_input`
- `status`

契約固有の追加フィールドはJSONモードで保持する。

## 9. Character Profile GUI

以下をフォーム入力可能にする。

- name
- personality
- speaking_style
- streaming_style
- existence.physical_capabilities
- existence.sensory_capabilities
- existence.experience_boundaries
- existence.world_relationship

配列項目は1行1件で入力する。

## 10. データ保持方針

- GUIで編集対象としていない未知フィールドは、可能な限り既存オブジェクトへマージして保持する。
- GUIで再構築する契約固定項目は、フォーム値を正とする。
- 高度な入れ子構造を完全にGUI化することは非目標とし、JSONモードを利用する。
- 入力内容はブラウザ内だけに保持し、DBやローカルファイルへ永続化しない。

## 11. API・バックエンド

API契約はv1.0.0から変更しない。

```text
POST /api/internal-directive
```

画面側だけでGUI値を既存JSON契約へ変換するため、`InternalDirectiveRequest`、PromptBuilder、Planner、Parserの責務は変更しない。

## 12. レスポンシブ設計

- スマートフォンでは1列表示を基本とする。
- タブレット・PCではフォームとメーターを2〜5列へ展開する。
- 入力モード切替は狭い画面で全幅表示する。
- JSON欄は等幅フォントと縦方向リサイズを維持する。

## 13. テスト方針

既存のAPI・認証・停止境界テストに加え、HTMLに以下が含まれることを確認する。

- GUI入力／JSON入力の切替
- `type="range"` の感情値入力
- 内部状態の視覚サマリー領域
- Activity追加操作
- JSONからGUIへ反映する操作

JavaScriptは静的構文検査を行い、ブラウザ実機では次を確認する。

- GUI値がJSONへ同期される
- JSON値がGUIへ同期される
- 不正JSONでGUIへ切り替わらない
- スライダー、数値、メーター、強度表示が連動する
- GUI入力のまま司令塔LLMを実行できる

## 14. 非目標

- 本番状態DBの直接編集
- 入力意味解析ラボとの自動通信
- 状態更新提案の適用
- Activity実行
- GUI入力項目の永続保存
- 任意の入れ子JSONを完全に自動フォーム化すること
