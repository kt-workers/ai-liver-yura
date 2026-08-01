# Activity候補 Safety要件正規契約・Shadow同等性評価設計

- Version: 1.0.0
- Status: Implemented
- 対象工程: 第11／14工程
- 前提:
  - `character_activity_candidate_execution_boundary_equivalence_shadow_design_v1.0.0.md`
  - `character_activity_candidate_authority_requirement_shadow_design_v1.0.0.md`
- 次工程: 第12工程 意味・実行境界の適用条件統合

## 1. 目的

MoralによるActivity候補選好を安全に適用できるか判断するには、候補同士が意味的に同等であるだけでなく、同じSafety要件を持つことを確認する必要がある。

第9工程では候補別Safety契約が存在しなかったため、Safety同等性を常に`unconfirmed`としていた。

本設計では、Activity候補が宣言するSafety要件の最小正規契約をShared Contractへ追加し、候補間の要件一致をShadowで評価する。

本工程ではSafety違反の検出、禁止、確認要求、実行許可を実装しない。

## 2. 工程進捗

全14工程のうち、本設計は第11工程に対応する。

1. Desire State基盤: 完了
2. Activity結果による欲望充足: 完了
3. Motivation Appraisal: 完了
4. Motivation候補選好: 完了
5. Moral Profile／Moral State観測: 完了
6. Moral候補選好Shadow: 完了
7. Activity候補の意味的同等性契約: 完了
8. Situation Evaluator証拠生成Shadow: 完了
9. Authority／Capability／Constraint／Safety同等性Shadow: 完了
10. Authority要件正規契約: 完了
11. Safety要件正規契約: 本工程
12. 意味・実行境界の適用条件統合: 未着手
13. 機能フラグ付き限定適用: 未着手
14. Response Content Planと連続会話評価: 未着手

## 3. 基本方針

### 3.1 宣言要件とSafety判定を分離する

`ActivitySafetyRequirement`は候補が従うSafety policyとRisk classを宣言する契約である。

この契約自体は、現在の入力、Constraint、外部状態、生成内容が安全かを判定しない。

```text
Safety requirement declaration
    !=
Safety evaluation result
    !=
Execution permission
```

### 3.2 未設定を安全扱いしない

`ActivityDefinition.safety_requirement is None`は、Safety要件が存在しないことではなく、候補別契約が未設定であることを意味する。

候補グループに未設定候補が1つでも含まれる場合、Safety同等性は`unconfirmed`とする。

### 3.3 Risk classだけで実行可否を決めない

Risk classは候補間の宣言要件を比較する分類であり、単独で次を行わない。

- Activityの禁止
- Activityの許可
- Confirmationの要求
- 優先順位変更
- Prompt内容の制限
- Plugin Commandの拒否

### 3.4 LLMを正本にしない

Safety要件はRuntimeまたはPluginが登録する型付き`ActivityDefinition`だけを正本とする。

LLM出力、ユーザー本文、Prompt自然言語、Desire、Motivation、MoralからSafety policyやRisk classを生成しない。

## 4. Shared Contract

### 4.1 Risk class

```python
class ActivitySafetyRiskClass(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"
```

本Versionの分類は比較用の契約値であり、Severity scoreや禁止閾値へ自動変換しない。

### 4.2 Safety要件

```python
@dataclass(frozen=True, slots=True)
class ActivitySafetyRequirement:
    policy_id: str
    risk_class: ActivitySafetyRiskClass
```

`policy_id`は、候補が従うSafety policyの安定識別子である。

例:

```text
core.conversation_safety.v1
core.external_action_safety.v1
streaming.public_output_safety.v1
```

表示名、説明文、LLM向け文言を`policy_id`として使用しない。

### 4.3 ActivityDefinitionへの追加

```python
@dataclass(frozen=True, slots=True)
class ActivityDefinition:
    ...
    authority_requirement: ActivityAuthorityRequirement | None = None
    safety_requirement: ActivitySafetyRequirement | None = None
```

既存Activity定義との互換性を維持するため任意項目とする。

ただし、`None`をSafety要件不要または安全確認済みとして解釈してはならない。

## 5. 契約値の検証

`ActivitySafetyRequirement`生成時に次を検証する。

- `policy_id`が文字列である
- 前後空白除去後の`policy_id`が空ではない
- `risk_class`が`ActivitySafetyRiskClass`である

文字列`"low"`をRisk classへ暗黙変換しない。

ConfigやPlugin manifestから生成する将来のAdapterは、Shared Contractへ渡す前に明示的に列挙値へ変換する。

## 6. Safety候補診断

候補ごとに次をShadow診断へ保持する。

```python
@dataclass(frozen=True, slots=True)
class SafetyCandidateAssessment:
    activity_type: str
    policy_id: str | None
    risk_class: str | None
```

Safety要件未設定または不正契約の場合、`policy_id`と`risk_class`は`None`とする。

この診断結果には、次を含めない。

- `safe`
- `allowed`
- `blocked`
- `violation`
- `current_request_safe`

本工程には現在入力をSafety policyへ評価する実装が存在しないためである。

## 7. Safety同等性評価

### 7.1 confirmed

candidate group内の全候補が明示的な`ActivitySafetyRequirement`を持ち、次が完全一致する場合に`confirmed`とする。

```text
policy_id
risk_class
```

### 7.2 rejected

全候補に契約が存在するが、`policy_id`または`risk_class`が1つでも異なる場合に`rejected`とする。

同じRisk classでもpolicy IDが異なる候補は同等とみなさない。

同じpolicy IDでもRisk classが異なる候補は同等とみなさない。

### 7.3 unconfirmed

次の場合は`unconfirmed`とする。

- candidate groupが不正
- Activity定義が不足
- 1候補でもSafety要件が未設定
- Safety要件が正規型ではない

情報不足を`confirmed`へ昇格しない。

## 8. Execution Boundary全体評価

第11工程完了後、次の4境界がすべて`confirmed`になり得る。

- Authority
- Capability
- Constraint
- Safety

全体評価規則は既存のままとする。

```text
いずれか rejected
    -> 全体 rejected

4境界すべて confirmed
    -> 全体 confirmed

それ以外
    -> 全体 unconfirmed
```

Execution Boundary全体が`confirmed`でも、Moral候補選好の実適用は許可しない。

```text
activation_permitted = false
```

## 9. Runtime接続

Situation Evaluator応答後の`SituationSemanticEquivalenceShadowObserver`で次を観測する。

```text
Situation analysis
    -> semantic equivalence evidence
    -> Moral hypothetical preference
    -> Authority equivalence
    -> Capability equivalence
    -> Constraint equivalence
    -> Safety equivalence
    -> diagnostic log
```

結果は同一ターンのSituation Evaluator、Behavior Planner、Activity Plan Validator、Plugin Commandへ戻さない。

## 10. 信頼境界

### 信頼するもの

- Runtime／Pluginが登録した型付き`ActivityDefinition`
- `ActivitySafetyRequirement`
- `ActivitySafetyRiskClass`

### 信頼しないもの

- LLMが生成したSafety policy ID
- LLMが生成したRisk class
- ユーザー本文中の「安全」「危険」という表現
- viewerの自己申告
- Activity表示名やdescriptionのキーワード
- Moral fit
- Desire／Motivation値

## 11. 維持する安全境界

本工程では次を変更しない。

- Activity候補集合
- `available_activities`の実順序
- active／ongoing／pinned候補
- 決定論Matcher
- ユーザーの明示意図
- 既存Authority判定
- Capability可用性判定と実行直前再検証
- Constraint validation
- Confirmation処理
- Safety違反判定
- Activity禁止
- Plugin Command実行可否
- Response Content Plan
- Character Response本文

Moralによる抑制とSafetyによる禁止も統合しない。

## 12. テスト方針

次を検証する。

- policy IDの前後空白が正規化される
- 空policy IDを拒否する
- 文字列Risk classを暗黙受理しない
- 同じpolicy ID／Risk classはSafety `confirmed`
- policy ID差はSafety `rejected`
- Risk class差はSafety `rejected`
- 契約未設定候補を含む場合はSafety `unconfirmed`
- 4実行境界すべてが明示同等なら全体`confirmed`になり得る
- 意味的同等性と4境界がすべて`confirmed`でも実候補順を変えない
- `activation_permitted=false`を維持する
- Architecture／Plugin／Runtime境界を維持する

## 13. 非対象

本Versionでは次を実装しない。

- Safety policy本文の定義
- Safety policy evaluator
- 入力・出力・ConstraintのSafety判定
- Risk classの数値化
- Risk classによる自動禁止
- Human approval契約
- Safety結果の永続化
- Safety設定YAML
- Plugin manifestからのSafety要件ロード
- 実行Validatorへの接続
- Moral候補順の実適用

## 14. 次工程

第12工程では、次の条件を1つの型付き適用条件へ統合する。

- Moral Shadowの静的適格性
- 意味的同等性`confirmed`
- Authority同等性`confirmed`
- Capability同等性`confirmed`
- Constraint同等性`confirmed`
- Safety同等性`confirmed`
- pinned／active／ongoing保護
- Motivation段階保護

第12工程もShadow判定に留め、実候補順変更は第13工程まで有効化しない。
