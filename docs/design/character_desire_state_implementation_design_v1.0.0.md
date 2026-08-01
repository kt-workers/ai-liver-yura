# キャラクター Desire State 観測基盤 実装設計

Version: 1.0.0

## 1. 位置づけ

本書は、`character_motivation_morality_design_report.md` の段階導入方針に基づき、
キャラクター動機・善悪設計の最初のコード実装として追加する Desire State 観測基盤を定義する。

検討レポートは実装仕様の確定版ではなく、初期値、値域、更新周期、減衰方式、
Activityごとの満足量などを未決事項としている。本実装では、それらを将来調整可能な
暫定値として定義する。

## 2. 目的

- 7種類の欲望を型付きDomain Stateとして保持する
- Eventおよび経過時間から決定論的に更新できるようにする
- satisfactionとfrustrationを観測できるようにする
- 既存のEmotion、Drive、Relationshipと別責務として扱う
- Behavior Planner、Activity選択、Character Responseにはまだ影響させない
- 後続のMotivation Appraisal導入前に値の推移をテスト可能にする

## 3. 対象となる欲望

| 欲望 | 識別子 | 初期baseline | 説明 |
|---|---|---:|---|
| 交流欲求 | `connection` | 0.45 | 誰かと関わり、関係を深めたい |
| 探索欲求 | `curiosity` | 0.50 | 未知の情報や刺激を得たい |
| 表現欲求 | `expression` | 0.40 | 考えや感情を外へ出したい |
| 承認欲求 | `recognition` | 0.30 | 認識され、評価され、役に立ちたい |
| 自律欲求 | `autonomy` | 0.40 | 自分で選び、自分の活動を持ちたい |
| 安全欲求 | `security` | 0.35 | 危険、不快、過負荷を避けたい |
| 達成欲求 | `achievement` | 0.35 | 目標を完了し、上達したい |

初期値はキャラクター設定の確定値ではない。観測結果を得るための暫定値であり、
後続でCharacter Profileまたは専用設定へ移動する。

## 4. Domain Model

### 4.1 DesireValue

各欲望は次を保持する。

- `level`: 現在の欲求水準
- `baseline`: 長期的な基準値
- `sensitivity`: Event変化量へ掛ける感度
- `satisfaction`: 最近満たされた度合い
- `frustration`: 満たされない状態の蓄積

すべての値域は `0.0..1.0` とし、生成時に範囲へclampする。

実効値は次で計算する。

```text
effective_level = clamp(level + frustration - satisfaction, 0.0, 1.0)
```

### 4.2 DesireState

7種類の`DesireValue`を不変値として保持する。

提供する操作:

- 識別子による取得
- 識別子による一項目の置換
- 実効値の辞書化
- 最も強い欲望の取得

## 5. Event更新仕様

第1実装では、既存Eventだけを使用する。新しいEvent種別は追加しない。
更新量は`DesireStateUpdater`へ閉じ込め、他のRuntime部品へ分散させない。

| Event | 主な更新 |
|---|---|
| `USER_TEXT` / `YOUTUBE_COMMENT` / `USER_SPEECH` | connection、curiosity、expressionを上げる |
| `USER_INTERACTION` | connectionとcuriosityを小さく上げる |
| `SILENCE_TIMEOUT` | connection、expression、frustrationを小さく上げる |
| `TREND_UPDATED` | curiosityを上げる |
| `STREAM_STARTED` | expression、recognition、achievementを上げる |
| `SPEECH_FINISHED` | expressionを満たし、connectionとachievementを少し満たす |
| `ACTION_FAILED` | achievementとsecurityを上げ、achievementのfrustrationを上げる |
| `STREAM_ENDED` | achievementとrecognitionを満たす |

Event更新は欲望を直接Activityへ変換しない。

## 6. 経過時間更新仕様

時間経過では次を行う。

- `level`を緩やかに`baseline`へ戻す
- `satisfaction`を減衰させる
- 実効的な不足が大きい場合だけ`frustration`を徐々に増やす
- 不足が小さい場合は`frustration`を減衰させる

最初の暫定係数:

- baseline回帰率: 1分あたり 4%
- satisfaction減衰: 1分あたり 0.08
- frustration増加: 不足量に対して1分あたり 0.04
- frustration減衰: 1分あたり 0.03

負の経過時間は0秒として扱う。

## 7. Runtime統合方針

最初の統合先は次とする。

```text
AgentEvent
  -> AgentEventStateUpdater
  -> DesireStateUpdater.update_by_event()
  -> AgentState.current_desire

Elapsed time
  -> ElapsedStateUpdater
  -> DesireStateUpdater.update_by_elapsed_time()
  -> AgentState.current_desire
```

`BehaviorPlanner`や`AutonomousEventPlanner`へDesireを渡さない。
既存のAgentState observerを通じて、更新後の値を観測境界へ渡す。

## 8. 観測方針

- AgentStateから7欲望の詳細値と実効値を取得できること
- Event更新と経過時間更新の結果をAgentState上で比較できること
- 既存UDPテレメトリへ`desire`セクションを追加すること
- テレメトリには各欲望の`level`、`baseline`、`sensitivity`、
  `satisfaction`、`frustration`、`effective_level`を含めること
- 本文、会話内容、個人情報をテレメトリへ追加しないこと

追加フィールドは診断用であり、本PRではGUI表示や
「こころの潮流」画面の表示項目・描画ロジックを変更しない。
既存クライアントは未知の`desire`フィールドを無視できるため、
テレメトリの`schema_version`は1を維持する。

## 9. 非対象

- Motivation Appraisal
- Moral Profile / Moral State
- Behavior Plannerの候補評価変更
- Response Content Plan
- Character LLMへのDesire注入
- DesireのDB永続化
- Character Profile設定化
- 外部Subsystem操作
- こころの潮流画面でのDesire可視化

## 10. テスト方針

- 各値が`0.0..1.0`へclampされる
- 実効値がsatisfactionとfrustrationを反映する
- 7欲望の初期値と識別子が固定される
- User input、silence、trend、speech finished、action failedの更新を検証する
- 経過時間でbaseline回帰、satisfaction減衰、frustration増減を検証する
- 未対応Eventでは状態を変更しない
- 負の経過時間では状態を変更しない
- UDPテレメトリに7欲望の詳細値が含まれる
- テレメトリ追加後も既存Emotion、Drive、Activity構造を維持する

## 11. 後続段階

1. 実会話ログから係数を調整
2. Motivation Appraisalを追加
3. Behavior Plannerへ読み取り専用入力として接続
4. Moral Profile / Moral Stateを追加
5. Response Content Planへ投影
6. 必要性を評価した後にGUI可視化を検討
