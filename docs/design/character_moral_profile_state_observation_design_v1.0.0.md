# Character Moral Profile / Moral State 観測設計

Version: 1.0.0

## 1. 位置づけ

本書は、`character_motivation_morality_design_report.md` の段階導入方針にある
「第4段階: Moral Profile / Moral State」を、現在のRuntime構造へ追加するための実装仕様である。

先行段階では、Desire State、Activity結果による充足評価、Motivation Appraisal、
Motivationによる許可済みActivity候補間の補助選好を追加した。

本段階では次を追加する。

- 長期価値判断傾向を表す`MoralProfile`
- 感情や状況で一時的に変わる`MoralState`
- ProfileとStateを合成した観測用要約
- Eventと経過時間による決定論的なState更新
- Activity候補ごとの観測用`moral_fit`
- 通常・自律Behavior PlanningとUDPテレメトリへの投影

本段階のMoral評価は観測専用であり、Activityの選択、並べ替え、禁止、抑制、
Capability、Authority、Constraint、Safety判定を変更しない。

## 2. 責務分離

### 2.1 Moral Profile

欲望をどのような方法で満たしやすいかを表す長期傾向である。

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

単一の善悪メーターは採用しない。

### 2.2 Moral State

感情や直近のActivity結果により一時的に変化する判断状態である。

```python
@dataclass(frozen=True, slots=True)
class MoralState:
    restraint: float
    empathy_activation: float
    selfish_impulse: float
    aggressive_impulse: float
    guilt: float
```

### 2.3 Safety / Authority / Capability

Moralはキャラクターの価値判断傾向であり、システムの許可境界ではない。

次の既存境界を維持する。

- Conversation Flow
- Authority
- Capability
- Activity Constraint
- execution claim validation
- Safety Policy
- Subsystem公開契約

## 3. 値域

全フィールドは`0.0`以上`1.0`以下とする。

- Profileは範囲外を構築時エラーとする
- Stateは範囲外を構築時エラーとする
- Stateの増減操作は`0.0`から`1.0`へクランプする
- Activity候補の`moral_fit`も`0.0`から`1.0`へクランプする

## 4. 暫定初期Profile

| 項目 | 初期値 |
|---|---:|
| compassion | 0.72 |
| honesty | 0.68 |
| fairness | 0.66 |
| altruism | 0.58 |
| rule_respect | 0.62 |
| dominance | 0.38 |
| competitiveness | 0.48 |
| jealousy_tendency | 0.28 |
| possessiveness | 0.24 |
| malice | 0.18 |

これらは「ゆら」を完全に定義する確定値ではない。
実ログと連続会話評価により調整するための暫定値である。

## 5. ProfileからのState基準値

Profileから、Moral Stateが時間経過で戻る基準値を決定論的に算出する。

概念式:

```text
restraint
= rule_respect + compassion - dominance

empathy_activation
= compassion + altruism

selfish_impulse
= dominance + possessiveness + malice

aggressive_impulse
= dominance + competitiveness + malice

guilt
= honesty + compassion
```

実装では各項目へ係数と定数項を適用し、`0.0`から`1.0`へクランプする。

## 6. ProfileとStateの合成

観測用に次の要約値を算出する。

| 項目 | 意味 |
|---|---|
| `prosocial_activation` | 向社会的Profile、共感活性、抑制の合成 |
| `adversarial_activation` | 対立的Profile、自己中心衝動、攻撃衝動の合成 |
| `effective_restraint` | 現在の抑制とProfile上の規範・思いやりの合成 |

これらはSafety判定ではなく、状態推移を比較する診断値である。

## 7. Eventによる更新

`MoralStateUpdater`は、現在StateをProfile・更新後Emotion・Relationshipから導出した
目標状態へ一部近づけた後、Event固有の増減を反映する。

### 7.1 感情による一時変化

- angerは`aggressive_impulse`を上げ、`restraint`を下げる方向へ作用する
- discomfortとfearは警戒として`restraint`へ作用する
- sadnessとdiscomfortは`guilt`へ弱く作用する
- emotional pressureは`selfish_impulse`と`aggressive_impulse`へ弱く作用する

感情値だけでActivityを禁止しない。

### 7.2 Event固有更新

| Event | 主な更新 |
|---|---|
| USER_TEXT / USER_SPEECH / YOUTUBE_COMMENT | empathy_activationを小さく上げる |
| USER_INTERACTION | empathy_activationを小さく上げる |
| ACTION_FAILED | guiltとrestraintを上げる |
| Activity failed | guiltとrestraintを上げる |
| Activity partial | guiltを小さく上げる |
| Activity canceled | guiltをわずかに上げる |
| Activity completed | guiltとaggressive_impulseを下げる |
| SPEECH_FINISHED | selfish_impulseとaggressive_impulseをわずかに下げる |

## 8. 経過時間更新

`ElapsedStateUpdater`から`MoralStateUpdater`を呼び出す。

- 負の経過時間は無視する
- Profile、減衰後Emotion、現在Relationshipから目標状態を算出する
- 15分で目標状態へ到達する暫定係数とする
- Event反映時刻をMoral更新の基準時刻として記録する

Profileは時間経過で変化させない。

## 9. AgentState統合

`AgentState`へ次を追加する。

```python
moral_profile: MoralProfile
current_moral: MoralState
```

`with_moral()`はStateだけを置換し、Profileを変更しない。

## 10. Motivation Appraisal統合

Motivation Appraisalへ次を追加する。

- `moral_evaluation_available`
- `moral_observation_only`
- Moral Profile
- Moral State
- Moral Composite

Moral ProfileとStateが与えられた場合:

```text
moral_evaluation_available = true
moral_observation_only = true
suppressed_activity_types = []
suppression_reasons = ["moral_fit_observation_only"]
```

片方だけを指定することは禁止する。

## 11. Activity候補のmoral fit

`MoralActivityCandidateEvaluator`は、既存Activity候補へ観測用の適合度を付与する。

```python
@dataclass(frozen=True, slots=True)
class MoralActivityCandidateFit:
    activity_type: str
    moral_fit: float
    profiled: bool
    observation_only: bool
    reason: str
```

### 11.1 計算方針

既知Activityには、Activity識別子ごとの型付きポリシーを割り当てる。
Activity説明文やユーザー入力のキーワードから善悪を推測しない。

概念式:

```text
moral_fit
= 0.5
+ Σ((profile_value - 0.5) × profile_weight)
+ Σ((state_value - 0.5) × state_weight)
```

### 11.2 初期ポリシー群

- social
- listening
- assertive
- ruled execution
- exploration
- observation

未知Activityは次の中立値とする。

```text
moral_fit = 0.5
profiled = false
reason = "unprofiled_activity_neutral"
```

未知Activityを候補から削除しない。

## 12. Situation Evaluator投影

Promptへ次を追加する。

- `planning_input.moral`
- `planning_input.activity_candidate_moral_fits`
- `available_activities[].moral_fit_observation`

Prompt規則で次を明示する。

```text
Moral Profile、Moral State、moral_fitは観測専用である。
候補の選択、並べ替え、禁止、抑制へ使用しない。
```

Motivationによる既存候補順は変更しない。

後続の`character_moral_activity_candidate_preference_shadow_design_v1.0.0.md`では、
実際の候補順を変更せず、`current_order`と`hypothetical_order`を比較する
Moral候補選好Shadow契約を定義する。

## 13. 自律Planning

`AutonomousMotivationContextBuilder`は、現在のProfileとStateを
Motivation Appraisalへ渡す。

自律Eventへ渡るMoral文脈も観測専用であり、次を変更しない。

- Driveによる自律発話開始判定
- Emotionによる発話抑制
- Conversation Flow
- 再試行間隔
- Activity候補順

## 14. UDPテレメトリ

既存`schema_version = 1`の追加フィールドとして`moral`を追加する。

```json
{
  "moral": {
    "profile": {},
    "state": {},
    "composite": {},
    "observation_only": true
  }
}
```

本文、ユーザー入力、秘密情報は含めない。

## 15. 本段階で変更しない範囲

- Moralによる候補の並べ替え
- MoralによるActivity禁止・抑制
- Safety Policyの置換
- AuthorityまたはCapabilityの変更
- Character Response内容
- Character LLMへの会話戦略注入
- Response Content Plan
- Moral ProfileのYAML設定
- Moral StateのDB永続化
- Relationship永続情報へのMoral値混入
- GUI表示
- Curiosity飽和問題

## 16. テスト方針

### 16.1 Domain

- Profileの10傾向
- ProfileとStateの値域検証
- ProfileからState基準値を導出できること
- ProfileとStateの合成値
- State増減のクランプ

### 16.2 Runtime

- angerで攻撃衝動が一時的に上がること
- Activity失敗でguiltが上がること
- Activity完了でguiltが下がること
- 経過時間でProfile基準値へ戻ること
- AgentEventStateUpdaterとElapsedStateUpdaterへ統合されること

### 16.3 Candidate

- ProfileとStateに応じて既知候補のmoral fitが変化すること
- 未知候補が中立値になること
- moral fitがMotivation候補順を変えないこと
- moral fitが候補を削除しないこと

### 16.4 Boundary

- 決定論Matcherを上書きしないこと
- Capability、Authority、Constraint、Safety境界を迂回しないこと
- CoreからPlugin／Subsystem具体実装への依存を追加しないこと

## 17. 後続工程

1. 実ログでMoral Stateの変動幅を観測する
2. Activity候補ごとのmoral fit分布を記録する
3. 初期Profileと更新係数を調整する
4. Moral候補選好Shadowの成立率と仮想順序差分を観測する
5. 意味的同等性を表す型付き評価契約を追加する
6. Moral抑制とSafety禁止を別の結果として表現する
7. Response Content Planへ価値判断と会話戦略を投影する
