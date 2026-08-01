# キャラクター動機・善悪設計 検討レポート

## 1. 文書の位置づけ

本書は、AI VTuber「ゆら」のキャラクター性を改善するために検討した、以下の概念の導入方針を整理するものである。

- 現在の感情状態
- 7種類の欲望
- 善悪を含む価値判断傾向
- 会話戦略およびActivity選択への反映

本書は実装仕様の確定版ではなく、既存実装を前提とした設計検討レポートである。

既存実装の記述は、`feature/plugin-separation-development` を基準に確認した。欲望、Moral Profile、Moral State、Motivation Appraisal、Response Content Planなどは今後追加を検討する概念であり、現在実装済みの要素とは明確に区別する。

## 2. 背景

現在のキャラクター応答には、以下の課題がある。

- 類似した発話や構文が繰り返される
- 共感、感想、軽い質問など、安全な応答パターンへ偏りやすい
- 状況へ反応はするが、キャラクター自身が何をしたいのかが弱い
- 感情が表情や声には反映されても、次の行動理由へ十分につながらない
- 常に無難で善良な応答へ寄せると、人格の不完全さや面白さが失われる

感情は「起きた出来事をどう感じたか」を表現できる一方、それだけでは「次に何をしたいか」を十分に説明できない。

そこで、感情とは別に欲望を導入し、さらに同じ欲望をどのような方法で満たそうとするかを変化させる価値判断傾向を導入する。

## 3. 現行実装との整合

### 3.1 三脳構造は採用していない

現在の実装では、三つの判断主体や、いわゆる三脳構造は採用していない。

欲望や善悪の概念は、複数人格を競合させる形ではなく、既存のSituation Analysis、Behavior Planning、会話生成を補助する内的状態として追加する。

### 3.2 現在の主要処理経路

現在の主要な処理経路は、概ね以下である。

```text
Event / Input
        ↓
Situation Evaluator
        ↓
Situation Analysis
        ↓
Behavior Planner
        ↓
Activity Plan
        ↓
Activity Execution / Result
        ↓
Action Planner
        ↓
Character Response Pipeline
        ↓
Action Plan Group
        ↓
Speak / Subtitle / Expression / Move 等
```

`BehaviorPlanner` は `ActivityPlan` を決定する。Activityの実行または結果確定後、`ActionPlanner` が `CharacterResponsePipeline` を利用し、発話、字幕、表情、ジェスチャーなどのActionへ変換する。

### 3.3 自律行動で現在参照している状態

自律行動では、`BehaviorPlanner` が以下を参照する。

- `drive_state`
- `emotion_state`
- 進行中Activity
- Situation Analysis
- active activity
- interrupted topicとの関係

現在確認できる自律判断では、`drive_state` の `energy` と、`emotion_state` の `talkativeness` が直接的な判断材料となり、待機、観察、無行動、自律発話などを選択する。

喜び、怒り、悲しみなど全感情を総合してActivityを選ぶ仕組みが既に完成している、という意味ではない。

### 3.4 責務はRuntime全体へ分散している

以下はすべてを `BehaviorPlanner` 単体が担当するものではない。

- 進行中Activityの扱い
- Capability確認
- Authority確認
- Activity制約
- 発話権
- 実行事実の検証
- 安全方針

現在の責務分担は概ね次の通りである。

| 境界・制御 | 主な担当 |
|---|---|
| Situationの意味評価 | Situation Evaluator |
| Activity候補とActivity Plan | Behavior Planner |
| Activity制約の検証 | Activity Constraint Validator、Activity計画・実行系 |
| CapabilityとProvider境界 | Plugin／Integration／Activity検証系 |
| 発話権と自律発話可否 | Conversation Flow State／Controller |
| Character応答生成 | Character Response Pipeline |
| 未実行操作の主張防止 | planner constraints、Character Prompt、Claim Validator、Response Validation |
| 発話・表情・動作への変換 | Action Planner |

今後、欲望や善悪を追加しても、この既存の責務分担を一つのクラスへ集中させない。

## 4. 現在実装済みの内的状態

### 4.1 Emotion State

現在の `EmotionState` は以下を持つ。

- `mood`
- `arousal`
- `valence`
- `talkativeness`
- `reactive`

現在の主な短期感情は以下である。

- `joy`
- `amusement`
- `anger`
- `sadness`
- `fear`
- `surprise`
- `discomfort`
- `emotional_pressure`

感情はCharacter Responseの文体、表情、声、間、reaction segmentなどへ反映される。

次の感情は本書の将来候補であり、現在の独立フィールドではない。

- `jealousy`
- `relief`
- `pride`
- `boredom`

状態更新例でこれらを用いる場合は、将来追加した場合の例として扱う。

### 4.2 Drive State

現在の自律判断では、少なくとも `energy` が使用される。

既存Driveを欲望と同一視しない。Driveは現在の活動可能性や内部活性を表す既存状態として維持し、Desireは「何を満たしたいか」を表す別責務とする。

### 4.3 Relationship State

現在の `RelationshipState` は以下を持つ。

- `counterpart_id`
- `display_name`
- `role`
- `familiarity`
- `trust`
- `affinity`
- `interaction_count`
- `last_interaction_at`
- `last_event_id`

現在の実装では、interaction記録により主に `familiarity` とinteraction情報が更新される。`trust` と `affinity` はモデル上存在するが、すべての出来事から自動更新する包括的な関係評価は未完成である。

次の項目は将来候補であり、現在の独立フィールドではない。

- 警戒
- 特別視
- 過去の衝突履歴
- 嫉妬対象
- 依存傾向

RelationshipがCharacter Responseへ渡され、表現判断の材料になるという既存方針は維持する。

### 4.4 Character Profile

現在の `CharacterProfile` は主に以下を保持する。

- name
- personality
- speaking style
- streaming style
- likes
- dislikes
- behavior policy
- existence profile

Trait、Desire baseline、Moral Profileは、現在の独立した型付き構造としては存在しない。

## 5. 基本概念の責務分離

### 5.1 Trait

長期的に変わりにくい性格傾向を表す。

候補:

- 社交性
- 警戒心
- 主導性
- 感情を表に出す強さ
- 冗談やからかいの傾向
- 自己開示のしやすさ

Traitは現在の自由記述中心のCharacter Profileを置き換えるのではなく、必要な部分から型付き補助情報として追加する。

### 5.2 Emotion

現在の出来事をどう感じているかを表す。

主な影響先:

- 刺激への反応
- 発話の調子
- 声
- 表情
- 間
- reaction segment

### 5.3 Desire

現在、何を満たしたいかを表す。

欲望は行動候補を生む内的な動機であり、Activity候補や会話戦略の評価材料となる。

### 5.4 Moral Tendency

欲望をどのような方法で満たすことを好むか、何を良いまたは悪いと感じやすいかを表す。

善悪は安全機構そのものではない。許可された候補の中で、キャラクターがどの方法を選びやすいかを変える。

### 5.5 Relationship

相手との関係に応じて、感情、欲望、価値判断をどこまで表へ出すかを決める。

### 5.6 Strategy

現在の感情、欲望、価値判断、関係状態を、具体的な会話行動へ変換する。

候補:

- 直接言う
- 遠回しに言う
- 軽くからかう
- 本音を隠す
- 自己開示する
- 相手へ譲る
- 主導権を取る

### 5.7 Safety / Authority / Capability

Characterの善悪傾向とは別に、システム境界を維持する。

#### 現在実装で確認できる主な境界

- Authority roleと入力の信頼性を区別する
- viewerの自己申告だけで管理者権限へ昇格しない
- 実行していない外部操作を実行済みと主張しない
- allowed／forbidden claimsと実行結果を応答検証へ利用する
- CapabilityとActivity定義を接続境界として扱う
- Activity制約を検証する
- 発話権をConversation Flowで管理する

#### 今後も維持・強化する安全方針

次は設計上必要だが、すべてが現在独立した決定論的検査器として完成しているとは限らない。

- ユーザーへ依存を強制しない
- 離脱や無反応へ罪悪感を与えない
- 脅迫しない
- 個人情報や秘密を悪用しない
- 欲望や悪意を現実的危害へ接続しない

## 6. 7種類の欲望

### 6.1 交流欲求 `connection`

誰かと関わりたい、反応してほしい、関係を深めたい欲望。

候補:

- ユーザーへ話しかける
- コメントへ反応する
- 過去の会話へ戻る
- 相手の状態を尋ねる
- 会話の継続を提案する

交流欲求が高くても、Conversation Flowの発話権や沈黙時ポリシーを越えない。

### 6.2 探索欲求 `curiosity`

知らないことを知りたい、新しい刺激を得たい欲望。

候補:

- 新しい話題を選ぶ
- 相手へ詳しく聞く
- 関連知識を参照する
- 観察を続ける
- 外部検索Capabilityが利用可能な場合、検索Activityを候補にする

外部検索Activityが常に利用可能な既存機能であるとは仮定しない。

### 6.3 表現欲求 `expression`

自分の考えや感情を外へ出したい欲望。

候補:

- 自律的に感想を話す
- 自己開示する
- 表情や声へ感情を漏らす
- 独り言を言う
- 対応Capabilityがある場合、歌、演技、創作を候補にする

### 6.4 承認欲求 `recognition`

自分を認識してほしい、評価してほしい、役に立ちたい欲望。

候補:

- 得意なことを見せる
- 努力や成果へ触れる
- ユーザーの役に立とうとする
- 配信成果や反応を気にする
- 褒められた出来事を記憶候補にする

### 6.5 自律欲求 `autonomy`

自分で選びたい、自分の活動や話題を持ちたい欲望。

候補:

- 自分で話題を選ぶ
- 順番や進め方を提案する
- 進行中Activityを継続したがる
- 軽い異論や反抗を示す
- 自分の好みを主張する

自律欲求はAuthorityや外部操作権限とは分離する。

### 6.6 安全欲求 `security`

危険、不快、過負荷、関係悪化を避けたい欲望。

候補:

- 不快な刺激から距離を取る
- 怪しい指示へ警戒する
- 活動量を下げる
- 話題を回避する
- Activityを停止または保留する

### 6.7 達成欲求 `achievement`

目標を完成させたい、上達したい、勝ちたい欲望。

候補:

- Activityを最後まで続ける
- 調査や企画を完了する
- 失敗した内容へ再挑戦する
- 過去の進捗を確認する
- 将来Game Subsystemが接続された場合、ゲーム内の勝利や上達を目指す

現在のCoreは旧Games Pluginやしりとり専用Activityを認識しない。ゲームに関する例は将来のGame Subsystem接続時の例として扱う。

## 7. 欲望状態のモデル案

```python
@dataclass(slots=True)
class DesireValue:
    level: float
    baseline: float
    sensitivity: float
    satisfaction: float
    frustration: float
```

- `level`: 現在どれだけ求めているか
- `baseline`: キャラクター固有の恒常的傾向
- `sensitivity`: 刺激へどれだけ反応しやすいか
- `satisfaction`: 最近どれだけ満たされたか
- `frustration`: 満たされない状態がどれだけ継続したか

概念式:

```text
effective_desire
= current level
+ frustration
- satisfaction
```

実際の計算式は、飽和、時間減衰、Activity結果、会話結果を含めて別途設計する。

## 8. 善悪の扱い

### 8.1 単一の善悪メーターは採用しない

`good = 0.8`、`evil = 0.2` のような一軸では、善人か悪人かを決めるだけになり、行動の多様性へ十分につながらない。

善悪は複数の価値判断傾向へ分解する。

### 8.2 向社会的傾向

- 思いやり `compassion`
- 誠実さ `honesty`
- 公平性 `fairness`
- 利他性 `altruism`
- 規範尊重 `rule_respect`

### 8.3 自己中心的・対立的傾向

- 支配性 `dominance`
- 競争心 `competitiveness`
- 嫉妬傾向 `jealousy_tendency`
- 独占欲 `possessiveness`
- 意地悪さ `malice`

後者をすべて禁止対象とはしない。適度な競争心、反抗、見栄、からかいは人格表現として利用できる。

ただし、ユーザーが嫌がっている、関係状態が悪化している、またはSafety Policyへ抵触する場合には抑制する。

## 9. Moral ProfileとMoral Stateの案

### 9.1 Moral Profile

```python
@dataclass(frozen=True, slots=True)
class MoralProfile:
    compassion: float
    honesty: float
    fairness: float
    altruism: float
    rule_respect: float
    dominance: float
    competitiveness: float
    jealousy_tendency: float
    possessiveness: float
    malice: float
```

### 9.2 Moral State

```python
@dataclass(slots=True)
class MoralState:
    restraint: float
    empathy_activation: float
    selfish_impulse: float
    aggressive_impulse: float
    guilt: float
```

Moral Profileは長期傾向、Moral Stateは感情や状況で一時的に変化する判断状態とする。

## 10. 欲望と善悪の組み合わせ

### 10.1 交流欲求

```text
connection 高
compassion 高
```

相手の負担を気にしながら会話を続けようとする。

```text
connection 高
dominance 高
```

少し強引に話題を続けたり、相手の反応を引き出そうとする。

### 10.2 承認欲求

```text
recognition 高
honesty 高
```

努力や成果を正直に見てもらおうとする。

```text
recognition 高
honesty 低
```

成果を少し大きく見せたり、失敗を軽くごまかす。

ただし、事実に反する外部操作・実績の主張は既存Claim境界で許可しない。

### 10.3 自律欲求

```text
autonomy 高
rule_respect 高
```

ルールや権限の範囲内で、自分の選択を主張する。

```text
autonomy 高
rule_respect 低
```

形式より面白さを優先し、軽い反抗や脱線を好む。

### 10.4 達成欲求

```text
achievement 高
fairness 高
```

正々堂々と成果を目指す。

```text
achievement 高
fairness 低
```

駆け引きや少しずるい方法を面白がる。

ゲームに関する具体例はGame Subsystem接続時の将来例とする。

## 11. 欲望同士および価値判断との葛藤

```text
connection 高
security 高
```

話しかけたいが警戒しているため、遠回しな表現になる。

```text
expression 高
recognition 高
honesty 中
```

本音を話したいが嫌われたくないため、言いかけて和らげる。

```text
autonomy 高
connection 高
```

自分の話を続けたいが、相手の話も聞きたいため、短く区切って発話権を返す。

```text
malice 中
compassion 高
```

軽くからかうが、相手の反応が悪ければ引き、後から少し気にする。

## 12. 行動候補の評価案

```python
@dataclass(frozen=True, slots=True)
class MotivationEvaluation:
    desire_gain: float
    emotional_fit: float
    relationship_fit: float
    moral_fit: float
    risk: float
    policy_allowed: bool
```

概念スコア:

```text
candidate_score =
    desire_gain
  + emotional_fit
  + relationship_fit
  + moral_fit
  - risk
```

`policy_allowed` が `False` の候補は採用しない。

欲望や善悪はActivityを直接実行する命令ではなく、候補評価の材料とする。

## 13. 現行パイプラインへの導入案

```text
Event / Situation
        ↓
Emotion Appraisal
        ↓
Emotion State
        ↓
Desire State Update
        ↓
Moral State Update
        ↓
Motivation Appraisal
        ↓
Situation Analysis
        ↓
Behavior Planner
        ↓
Activity Plan
        ↓
Activity Execution / Result
        ↓
Action Planner
        ↓
Response Content Plan
        ↓
Character Response Pipeline
        ↓
Action Plan Group
```

`Response Content Plan` の正確な配置は実装時に確定する。Activity結果からCharacter Responseを生成する現在の境界を壊さず、Action PlannerとCharacter Response Pipelineの責務を再確認して配置する。

### 13.1 Motivation Appraisal

- 上位の欲望
- 欲望同士の競合
- 価値判断上の抑制
- Relationshipによる表出強度
- 推奨Activity候補
- 推奨会話戦略

### 13.2 Behavior Planner

Behavior Plannerは引き続きActivity Planの決定を担当する。

欲望やMoral Stateを入力へ追加しても、発話権、Capability、Authority、Claim Validationなど、他コンポーネントの責務をBehavior Plannerへ吸収しない。

### 13.3 Character Response Pipeline

現在はResponse ContextやCharacter Profileを構造化JSONとしてCharacter LLMへ渡している。

DesireやMoralの追加時には、すべての生値をそのまま追加するのではなく、上位欲望、主要な葛藤、採用済み会話戦略を短い構造化文脈へ投影する案とする。

## 14. Subsystemとの境界

最新構造では、StreamingやGameはCore内部の具体実装ではなく、独立Subsystemとして扱う方向へ移行している。

### 14.1 Streaming

欲望や会話戦略がOBSやYouTube Adapterを直接操作しない。

```text
Character Motivation
        ↓
Core側Activity候補
        ↓
Authority / Confirmation / Capability
        ↓
Streaming公開契約
        ↓
Streaming Subsystem
```

### 14.2 Game

現在のCoreには旧Games Pluginやしりとり専用実装は存在しない。

Gameに関する欲望や善悪の例は、将来Game Subsystemが接続された場合の動作例として扱う。

### 14.3 External Search

検索Capabilityが存在する場合のみ、探索欲求から外部検索Activityを候補化する。未接続時は通常会話、内部知識、観察などへフォールバックする。

## 15. キャラクター表現上の方針

### 15.1 内部値を直接発話しない

避ける表現:

- 「交流欲求が上がっている」
- 「善性が高い」
- 「意地悪さが0.4ある」

自然な表現:

- 「もう少し話してたいかも」
- 「褒められると、やっぱりうれしい」
- 「ちょっとだけ困らせたくなった」

### 15.2 欲望は常に満たさない

欲望が高くても、Relationship、Activity、発話権、価値判断、Authority、Capabilityによって抑制される。

### 15.3 不完全さを残す

適度であれば人格を豊かにする候補:

- 嫉妬
- 見栄
- 競争心
- 軽い意地悪
- 反抗
- 独占欲
- 根に持つ
- 後悔や罪悪感

これらを現実的危害、依存、脅迫、罪悪感による強制へ接続しない。

## 16. 状態更新例

以下は将来状態を追加した場合の例である。現在未実装の感情名を含む。

### 16.1 ユーザーから褒められた

```text
Emotion:
joy 上昇
将来prideを追加する場合はpride上昇

Desire:
recognition が一時的に満たされる
connection が少し上昇
expression が少し上昇

候補:
短く喜ぶ
努力を少し自己開示する
相手への感謝を返す
```

### 16.2 長時間反応がない

```text
Emotion:
将来boredomを追加する場合はboredom上昇
sadnessがわずかに上昇する可能性

Desire:
connection 上昇
expression 上昇

制約:
沈黙を「続きを求めている」と解釈しない
相手へ罪悪感を与えない

候補:
Conversation Flowが許可する場合のみ短い自律話題
観察を続ける
別Activityへ移る
```

### 16.3 他のキャラクターが褒められた

```text
Emotion:
将来jealousyを追加する場合はjealousy上昇

Desire:
recognition 上昇
achievement 上昇

候補:
冗談交じりに対抗心を見せる
自分も頑張ると宣言する
少しだけ拗ねる
```

## 17. 段階導入

### 第1段階: 観測と定義

- 現在のDrive StateとEmotion Stateの更新元を整理する
- 発話目的、質問率、自己開示率、反復率を計測する
- 7欲望それぞれの増減イベントを定義する
- 実装済み状態と将来状態の用語表を作る

### 第2段階: Desire State

- `DesireState` と更新サービスを追加する
- Activity結果から満足・不満を更新する
- diagnostic snapshotへ値を追加する
- Behavior Plannerの判断はまだ変更せず観測のみ行う

### 第3段階: Motivation Appraisal

- 上位欲望と競合を算出する
- 推奨Activity候補と会話戦略を出力する
- Behavior Plannerへ読み取り専用入力として追加する

### 第4段階: Moral Profile / Moral State

- Character Profileから価値判断傾向を分離する
- 感情による一時的な抑制変化を追加する
- Activity候補へ `moral_fit` を付与する

### 第5段階: 発話計画

- `ResponseContentPlan` の責務と配置を確定する
- 上位欲望、葛藤、会話戦略、終了方針をCharacter LLMへ渡す
- 内部値の直接説明を禁止する
- 反復検知と会話戦略履歴を統合する

### 第6段階: 調整と評価

- 10から30ターンの連続会話で評価する
- 同じ発話構造への偏りを測定する
- 欲望が質問過多や自律発話過多を生んでいないか確認する
- 意地悪、嫉妬、独占欲が不快または依存的な表現へ逸脱していないか確認する

## 18. テスト方針

### 18.1 ドメイン

- 欲望値の増減、減衰、飽和
- satisfactionとfrustrationの更新
- Moral ProfileとMoral Stateの合成
- 競合する欲望の優先順位
- policy禁止候補の排除

### 18.2 Behavior Planning

- 欲望が高くても進行中Activityを壊さない
- Capability不足Activityを選ばない
- 自律欲求が高くてもAuthority境界を越えない
- 発話権制御を迂回しない
- 外部Subsystemへ直接依存しない

### 18.3 Character Response

- 内部パラメータ名を発話しない
- 同一欲望でもMoral Profileにより表現が変わる
- 嫉妬や意地悪さが攻撃へ直結しない
- 毎回質問で終わらない
- 実行していない操作を実行済みと主張しない

### 18.4 長期会話

- 発話目的の分布
- 応答戦略の分布
- 質問終了率
- 自己開示率
- 自律発話率
- 同じ話題への回帰率
- 文頭・文末パターンの反復率
- 欲望ごとのActivity選択率
- Moral Profileごとの表現差

## 19. 未決事項

- 各欲望の初期値
- 値域
- 更新周期
- 時間減衰方式
- 感情から欲望への変換係数
- Activityごとの満足量
- Moral Profileの設定形式
- Moral Stateの永続化
- 欲望を長期記憶へ保存するか
- LLM評価と決定論的評価の分担
- Response Content Planの正確な配置
- 追加感情の種類
- Relationship拡張項目
- 最初に接続するActivity

## 20. 結論

感情に欲望を追加すると、ゆらは出来事へ反応するだけでなく、自分が何を求めているかに基づいて行動候補を持てる。

さらに善悪を単純な善人・悪人の一軸ではなく、思いやり、誠実さ、公平性、規範尊重、支配性、競争心、嫉妬傾向、独占欲、意地悪さなどの価値判断傾向として導入すると、同じ欲望に対して異なる満たし方を選べる。

推奨する基本構造は以下である。

```text
Trait
Emotion
Drive
Desire
Moral Tendency
Relationship
Strategy
```

この内側でキャラクターらしい葛藤と不完全さを表現する。

外側では、既存Runtime全体に分散している以下の境界を維持する。

- Conversation Flow
- Authority
- Capability
- Activity constraints
- execution claim validation
- Safety policy
- Subsystem公開契約

実装は、まずDesire Stateを観測専用で追加し、その後Motivation Appraisal、Moral Profile、Response Content Planへ段階的に拡張する方針が安全である。
