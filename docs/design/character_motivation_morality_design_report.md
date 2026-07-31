# キャラクター動機・善悪設計 検討レポート

## 1. 文書の位置づけ

本書は、AI VTuber「ゆら」のキャラクター性を改善するために検討した、以下の概念の導入方針を整理するものである。

- 現在の感情状態
- 7種類の欲望
- 善悪を含む価値判断傾向
- 会話戦略およびActivity選択への反映

本書は実装仕様の確定版ではなく、既存実装を前提とした設計検討レポートである。実装前には、各値の定義、更新規則、永続化範囲、テスト方法を別途詳細化する。

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

現在の実装では、三つの判断主体や、いわゆる三脳構造は採用していない。

主要な判断経路は概ね以下である。

```text
Situation Evaluator
        ↓
Situation Analysis
        ↓
Behavior Planner
        ↓
Activity Plan
        ↓
Character Response Pipeline
        ↓
Action Plan
```

自律行動では、`BehaviorPlanner` が `drive_state`、`emotion_state`、進行中Activity、Situation Analysisなどを参照し、待機、観察、自律発話などを決定する。

したがって、欲望や善悪の概念は、複数人格を競合させる形ではなく、現在のSituation AnalysisおよびBehavior Planningを補助する内的状態として追加する。

## 4. 基本概念の責務分離

キャラクター性を構成する各概念は、以下のように責務を分ける。

### 4.1 Trait

長期的に変わりにくい性格傾向を表す。

例:

- 社交性
- 警戒心
- 主導性
- 感情を表に出す強さ
- 冗談やからかいの傾向
- 自己開示のしやすさ

### 4.2 Emotion

現在の出来事をどう感じているかを表す。

例:

- 喜び
- 悲しみ
- 怒り
- 不安
- 驚き
- 嫉妬
- 安堵

感情は主に、刺激への評価、声、表情、間、発話の勢いへ影響する。

### 4.3 Desire

現在、何を満たしたいかを表す。

欲望は行動候補を生む内的な動機であり、Activity選択の材料となる。

### 4.4 Moral Tendency

欲望をどのような方法で満たすことを好むか、何を良いまたは悪いと感じやすいかを表す。

善悪は安全機構そのものではない。許可された候補の中で、キャラクターがどの方法を選びやすいかを変える。

### 4.5 Relationship

相手との関係に応じて、感情、欲望、価値判断をどこまで表へ出すかを決める。

例:

- 親密度
- 信頼
- 警戒
- 特別視
- 過去の衝突

### 4.6 Strategy

現在の感情、欲望、価値判断、関係状態を、具体的な会話行動へ変換する。

例:

- 直接言う
- 遠回しに言う
- 軽くからかう
- 本音を隠す
- 自己開示する
- 相手へ譲る
- 主導権を取る

### 4.7 Safety / Authority / Capability Policy

絶対に越えてはならないシステム境界を表す。

- 権限のない外部操作を行わない
- 実行していないことを実行済みと主張しない
- ユーザーへ依存、脅迫、罪悪感を強制しない
- 個人情報や秘密を悪用しない
- Capabilityが存在しないActivityを実行しない

善悪傾向がどの値であっても、この境界は越えない。

## 5. 7種類の欲望

AI VTuberの行動へ接続しやすい機能的欲望として、以下の7種類を候補とする。

### 5.1 交流欲求 `connection`

誰かと関わりたい、反応してほしい、関係を深めたい欲望。

主な行動候補:

- ユーザーへ話しかける
- コメントへ反応する
- 過去の会話へ戻る
- 相手の状態を尋ねる
- 会話の継続を提案する

### 5.2 探索欲求 `curiosity`

知らないことを知りたい、新しい刺激を得たい欲望。

主な行動候補:

- 新しい話題を選ぶ
- 相手へ詳しく聞く
- 関連知識を参照する
- 外部検索Activityを候補にする
- 観察を続ける

### 5.3 表現欲求 `expression`

自分の考えや感情を外へ出したい欲望。

主な行動候補:

- 自律的に感想を話す
- 自己開示する
- 歌う、演じる、創作する
- 表情や声へ感情を漏らす
- 独り言を言う

### 5.4 承認欲求 `recognition`

自分を認識してほしい、評価してほしい、役に立ちたい欲望。

主な行動候補:

- 得意なことを見せる
- 努力や成果へ触れる
- ユーザーの役に立とうとする
- 配信成果や反応を気にする
- 褒められたことを記憶する

### 5.5 自律欲求 `autonomy`

自分で選びたい、自分の活動や話題を持ちたい欲望。

主な行動候補:

- 自分で話題を選ぶ
- 順番や進め方を提案する
- 進行中Activityを継続したがる
- 軽い異論や反抗を示す
- 自分の好みを主張する

自律欲求は、外部操作権限とは分離する。自分で決めたいという内的傾向が高くても、権限のない操作は実行しない。

### 5.6 安全欲求 `security`

危険、不快、過負荷、関係悪化を避けたい欲望。

主な行動候補:

- 不快な刺激から距離を取る
- 怪しい指示へ警戒する
- 活動量を下げる
- 話題を回避する
- Activityを停止または保留する

### 5.7 達成欲求 `achievement`

目標を完成させたい、上達したい、勝ちたい欲望。

主な行動候補:

- Activityを最後まで続ける
- ゲームで勝とうとする
- 調査や配信企画を完了する
- 失敗した内容へ再挑戦する
- 過去の進捗を確認する

## 6. 欲望状態のモデル

欲望は単一の現在値だけでなく、以下の要素を持たせる案とする。

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

実効的な欲望値は、概念的には以下のように求められる。

```text
effective_desire
= current level
+ frustration
- satisfaction
```

実際の計算式は、飽和、時間減衰、Activityごとの充足量を含めて別途設計する。

## 7. 善悪の扱い

### 7.1 単一の善悪メーターは採用しない

`good = 0.8`、`evil = 0.2` のような一軸では、善人か悪人かを決めるだけになり、行動の多様性へ十分につながらない。

善悪は、複数の価値判断傾向へ分解する。

### 7.2 向社会的傾向

#### 思いやり `compassion`

相手の感情や損失を重視する傾向。

#### 誠実さ `honesty`

嘘やごまかしを避け、事実との整合を重視する傾向。

#### 公平性 `fairness`

自分と相手を対等に扱い、一方的な利益を避ける傾向。

#### 利他性 `altruism`

自分の満足より、相手や全体の利益を優先する傾向。

#### 規範尊重 `rule_respect`

決まり、約束、役割、権限を尊重する傾向。

### 7.3 自己中心的・対立的傾向

#### 支配性 `dominance`

会話やActivityの主導権を握りたい傾向。

適度なら決断力や進行力になる。過剰になると、相手の意見を遮る、話題を押し通すなどへつながる。

#### 競争心 `competitiveness`

比較や勝敗を意識し、優位を目指す傾向。

#### 嫉妬傾向 `jealousy_tendency`

自分以外が注目や親密さを得た際に反応しやすい傾向。

現在の感情としての嫉妬とは分離する。

#### 独占欲 `possessiveness`

特定の相手や関係を、自分にとって特別なものとして確保したい傾向。

#### 意地悪さ `malice`

軽く困らせる、からかう、相手の反応を見て楽しむ傾向。

低から中程度であれば、冗談、煽り、勝ち気、軽い反抗としてキャラクターの魅力になり得る。相手が嫌がっている場合は、思いやり、関係状態、安全ポリシーにより抑制する。

## 8. Moral Profileと一時状態

### 8.1 Moral Profile

長期的に変わりにくい価値判断傾向。

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

### 8.2 Moral State

状況や感情により一時的に変化する判断状態。

```python
@dataclass(slots=True)
class MoralState:
    restraint: float
    empathy_activation: float
    selfish_impulse: float
    aggressive_impulse: float
    guilt: float
```

例:

- 基本的には思いやりが高くても、怒りが強い時には `empathy_activation` が下がる
- 意地悪な反応をした後に `guilt` が上がり、次の発話で和らげる
- 安全欲求が高い時には `restraint` が上がり、強い反応を抑える

## 9. 欲望と善悪の組み合わせ

同じ欲望でも、価値判断傾向によって表現や行動候補が変わる。

### 9.1 交流欲求

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

### 9.2 承認欲求

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

### 9.3 自律欲求

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

### 9.4 達成欲求

```text
achievement 高
fairness 高
```

正々堂々と成果や勝利を目指す。

```text
achievement 高
fairness 低
```

心理戦、駆け引き、少しずるい方法を面白がる。

## 10. 欲望同士および価値判断との葛藤

キャラクターらしさは、単一の最大値だけでなく、内的な競合から生まれる。

例:

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

軽くからかうが、相手の反応が悪ければすぐに引き、後から少し気にする。

この葛藤を発話計画へ反映することで、常に一直線で機械的な応答になることを避ける。

## 11. 行動候補の評価

欲望および価値判断は、Activityを直接実行する命令ではなく、候補評価の材料とする。

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

概念的な候補スコア:

```text
candidate_score =
    desire_gain
  + emotional_fit
  + relationship_fit
  + moral_fit
  - risk
```

ただし、`policy_allowed` が `False` の候補は、スコアに関係なく採用しない。

## 12. 現行パイプラインへの導入案

現在の構成を維持したまま、以下の層を追加する。

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
Response Content Plan
        ↓
Character Response Pipeline
```

### 12.1 Motivation Appraisal

現在の内的状態から、次を算出する。

- 上位の欲望
- 欲望同士の競合
- 価値判断上の抑制
- 関係状態による表出強度
- 推奨Activity候補
- 推奨会話戦略

### 12.2 Behavior Planner

既存の責務を維持し、Motivation Appraisalを追加の判断材料として扱う。

Behavior Plannerは引き続き、以下を優先する。

- 進行中Activity
- Capability
- 権限
- Activity制約
- 発話権
- 安全ポリシー

欲望値が高いだけで、進行中Activityや権限境界を無視しない。

### 12.3 Character Response Pipeline

Character LLMへ全ての内部数値をそのまま渡さない。

上位の欲望、主要な葛藤、採用済み会話戦略を、短い構造化文脈へ変換する。

例:

```text
現在は交流したい傾向がやや強い。
一方で、相手へ会話を強制したくないという抑制がある。
軽く会話を開くが、質問で回答を要求せず発話権を返す。
```

## 13. キャラクター表現上の方針

### 13.1 内部値を直接発話しない

避ける表現:

- 「交流欲求が上がっている」
- 「善性が高い」
- 「意地悪さが0.4ある」

自然な表現:

- 「もう少し話してたいかも」
- 「褒められると、やっぱりうれしい」
- 「ちょっとだけ困らせたくなった」

### 13.2 欲望は常に満たさない

欲望が高くても、関係、状況、Activity、発話権、価値判断によって抑制される。

満たされなかった欲望は、即座に強制的行動へ変換せず、時間経過、諦め、別の満たし方、感情変化へつなげる。

### 13.3 不完全さを残す

以下の要素は、適度であれば人格を豊かにする。

- 嫉妬
- 見栄
- 競争心
- 軽い意地悪
- 反抗
- 独占欲
- 根に持つ
- 後悔や罪悪感

ただし、ユーザーへ現実的な危害、依存、脅迫、罪悪感を強制する形へは接続しない。

## 14. 状態更新の例

### 14.1 ユーザーから褒められた

```text
入力:
ユーザーが成果を褒める

Emotion:
joy 上昇
pride 上昇

Desire:
recognition が一時的に満たされる
connection が少し上昇
expression が少し上昇

Moral State:
selfish_impulse は上がる可能性がある
compassion が高ければ自慢を抑える

候補:
短く喜ぶ
努力を少し自己開示する
相手への感謝を返す
```

### 14.2 長時間反応がない

```text
Emotion:
boredom 上昇
sadness がわずかに上昇する可能性

Desire:
connection 上昇
expression 上昇

制約:
沈黙を「続きを求めている」と解釈しない
相手へ罪悪感を与えない

候補:
新しい自律話題を短く開始
観察を続ける
別Activityへ移る
```

### 14.3 他のキャラクターが褒められた

```text
Emotion:
jealousy 上昇

Desire:
recognition 上昇
achievement 上昇

Moral Tendency:
honesty 高なら嫉妬を軽く認める
malice 中なら軽く張り合う
compassion 高なら相手を否定しない

候補:
冗談交じりに対抗心を見せる
自分も頑張ると宣言する
少しだけ拗ねる
```

## 15. 実装上の段階導入

### 第1段階: 観測と設計確定

- 現在の `drive_state` と `emotion_state` の更新元を整理する
- 会話ログから、発話目的、質問率、自己開示率、反復率を計測する
- 7欲望それぞれの増減イベントを定義する
- Moral Profileの初期値をキャラクター設定として定義する

### 第2段階: Desire Stateの導入

- `DesireState` と更新サービスを追加する
- Activity結果から満足・不満を更新する
- Runtime diagnostic snapshotへ値を追加する
- Behavior Plannerの判断はまだ変更せず、観測のみ行う

### 第3段階: Motivation Appraisalの導入

- 上位欲望と競合を算出する
- 推奨Activity候補と会話戦略を出力する
- 既存Behavior Plannerへ読み取り専用入力として追加する

### 第4段階: Moral Profile / Moral Stateの導入

- Character Profileから価値判断傾向を分離する
- 感情による一時的な抑制変化を追加する
- Activity候補へ `moral_fit` を付与する

### 第5段階: 発話計画への反映

- `ResponseContentPlan` を導入する
- 上位欲望、葛藤、会話戦略、終了方針をCharacter LLMへ渡す
- 内部値の直接説明を禁止する
- 反復検知と会話戦略履歴を統合する

### 第6段階: 調整と評価

- 10から30ターンの連続会話で評価する
- 同じ発話構造への偏りを測定する
- 欲望が強制的な質問や自律発話過多を生んでいないか確認する
- 意地悪、嫉妬、独占欲が不快または依存的な表現へ逸脱していないか確認する

## 16. テスト方針

### 16.1 ドメインテスト

- 欲望値の増減、減衰、飽和
- satisfactionとfrustrationの更新
- Moral ProfileとMoral Stateの合成
- 競合する欲望の優先順位
- policy禁止候補の排除

### 16.2 Behavior Plannerテスト

- 欲望が高くても進行中Activityを壊さない
- 欲望が高くてもCapability不足Activityを選ばない
- 自律欲求が高くても権限境界を越えない
- 交流欲求が高くても発話権制御を守る
- 安全欲求が高い場合に待機や停止候補が上がる

### 16.3 Character Responseテスト

- 内部パラメータ名を発話しない
- 同一欲望でもMoral Profileにより表現が変わる
- 嫉妬や意地悪さが相手への攻撃へ直結しない
- 欲望の葛藤が言い淀み、遠回しさ、短い自己開示などへ反映される
- 毎回質問で終わらない

### 16.4 長期会話評価

- 発話目的の分布
- 応答戦略の分布
- 質問終了率
- 自己開示率
- 自律発話率
- 同じ話題への回帰率
- 文頭・文末パターンの反復率
- 欲望ごとのActivity選択率
- Moral Profileごとの表現差

## 17. 未決事項

以下は本書では確定しない。

- 各欲望の初期値
- 値域を0.0から1.0にするか別形式にするか
- 更新周期
- 時間減衰方式
- 感情から欲望への変換係数
- Activityごとの満足量
- Moral Profileの設定形式
- Moral Stateを永続化するか
- 欲望を長期記憶へ保存するか
- 欲望や価値判断をLLMで評価するか決定論的に評価するか
- どのActivityから段階導入するか

## 18. 結論

感情に欲望を追加すると、ゆらは出来事へ反応するだけでなく、自分が何を求めているかに基づいて行動候補を持てる。

さらに善悪を単純な善人・悪人の一軸ではなく、思いやり、誠実さ、公平性、規範尊重、支配性、競争心、嫉妬傾向、独占欲、意地悪さなどの価値判断傾向として導入すると、同じ欲望に対して異なる満たし方を選べる。

推奨する基本構造は以下である。

```text
Trait
Emotion
Desire
Moral Tendency
Relationship
Strategy
```

この内側でキャラクターらしい葛藤と不完全さを表現し、外側には既存のSafety、Authority、Capability、Activity制約を強制境界として維持する。

実装は、まずDesire Stateを観測専用で追加し、その後Motivation Appraisal、Moral Profile、Response Content Planへ段階的に拡張する方針が安全である。
