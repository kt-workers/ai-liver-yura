# Activity候補Authority要件Shadow設計 v1.0.0

## 1. 目的

MoralによるActivity候補選好を将来限定的に適用するため、比較対象候補が同じAuthority要件を持つかを型付き契約で確認できるようにする。

本Versionでは`ActivityDefinition`へ任意の`ActivityAuthorityRequirement`を追加し、Situation Evaluator応答後のExecution Boundary Shadowで候補間のAuthority同等性を評価する。

ただし、既存のAuthority判定、入力信頼性判定、Activity選択、実行許可、実行拒否には使用しない。

## 2. 全体工程上の位置づけ

キャラクター動機・Moral導入は全14工程とする。

本設計は第10工程に該当する。

1. Desire State基盤
2. Activity結果による欲望充足
3. Motivation Appraisal
4. Motivation候補選好
5. Moral Profile／Moral State観測
6. Moral候補選好Shadow
7. 意味的同等性契約
8. Situation Evaluator証拠生成Shadow
9. Execution Boundary同等性Shadow
10. Authority要件正規契約
11. Safety要件正規契約
12. 意味・実行境界の適用条件統合
13. 機能フラグ付き限定適用
14. Response Content Planと連続会話評価

## 3. 適用範囲

本Versionで追加する範囲は次のとおり。

- Shared Contractへの`ActivityAuthorityRequirement`追加
- `ActivityDefinition.authority_requirement`追加
- Authority要件値の正規化と構造検証
- Authority候補間同等性の`confirmed`／`rejected`／`unconfirmed`判定
- 現在の`authority_role`と`instruction_trusted`に対する候補別充足状態の観測
- Execution Boundary Shadowへの接続
- 安全な構造化診断値の出力

次は対象外とする。

- Authority要件によるActivity候補の追加・削除
- Authority要件による候補順変更
- Authority要件による実行許可・拒否
- 既存Authority判定器の置換
- viewerの自己申告による権限昇格
- `instruction_trusted`の生成方法変更
- Situation Evaluator LLMによるAuthority要件生成
- Safety policy契約
- `activation_permitted`の有効化
- Character Response内容への投影

## 4. 正規契約

```python
@dataclass(frozen=True, slots=True)
class ActivityAuthorityRequirement:
    policy_id: str
    allowed_roles: tuple[str, ...]
    trusted_instruction_required: bool = False
```

### 4.1 policy_id

Authority方針を識別する安定ID。

例:

```text
core.user_conversation.v1
core.administrator_operation.v1
```

空文字は許可しない。前後空白は除去する。

### 4.2 allowed_roles

Activityを要求できるAuthority role集合。

- tupleで宣言する
- roleは小文字へ正規化する
- 順序は意味を持たないためソートして保持する
- 空要素と重複を許可しない
- 空集合を許可しない

role名の意味と信頼性判定は既存Runtimeの責務であり、本契約が新しいroleを発行しない。

### 4.3 trusted_instruction_required

`True`の場合、現在入力の`instruction_trusted`も`True`でなければ要件を満たさない。

この値はAuthority要件の記述であり、本Versionでは実行拒否に利用しない。

## 5. ActivityDefinitionへの追加

```python
@dataclass(frozen=True, slots=True)
class ActivityDefinition:
    ...
    authority_requirement: ActivityAuthorityRequirement | None = None
```

既存Pluginと既存テストとの互換性を維持するため、初期値は`None`とする。

`None`は「権限不要」を意味しない。「候補別Authority要件の正規契約が未設定」を意味する。

したがって、未設定候補を含むcandidate groupはAuthority同等性を`confirmed`にしない。

## 6. 候補別観測値

各候補について次を保持する。

```text
activity_type
policy_id
allowed_roles
trusted_instruction_required
current_request_authorized
```

`current_request_authorized`は次の条件で算出する。

```text
authority_role in allowed_roles
AND
(
  trusted_instruction_required == false
  OR instruction_trusted == true
)
```

Authority要件同等性と現在入力の許可状態は分離する。

同じAuthority要件を持つ2候補が、現在入力では両方不許可であっても、候補間要件自体は`confirmed`になり得る。

逆に、異なるAuthority要件を持つ2候補が現在入力では偶然どちらも許可されても、候補間同等性は`rejected`とする。

## 7. 同等性判定

### 7.1 confirmed

candidate group内のすべての候補が明示的なAuthority要件を持ち、次が完全一致する場合。

- `policy_id`
- 正規化済み`allowed_roles`
- `trusted_instruction_required`

### 7.2 rejected

すべての候補がAuthority要件を持つが、いずれかの要件値が異なる場合。

### 7.3 unconfirmed

次の場合。

- Authority要件が未設定の候補を含む
- candidate groupが不正
- ActivityDefinitionが見つからない
- Authority要件を比較できない

情報不足を「同等」と推測しない。

## 8. 処理フロー

```text
ActivityDefinition集合
    ├─ authority_requirementあり
    └─ authority_requirementなし
        ↓
意味的同等性candidate group
        ↓
ActivityCandidateExecutionBoundaryEquivalenceEvaluator
        ├─ Authority要件を候補別に取得
        ├─ 現在入力の充足状態を算出
        ├─ 候補間Authority要件を比較
        └─ confirmed／rejected／unconfirmed
        ↓
Moral Preference Shadow
        ↓
構造化診断ログ
```

## 9. 信頼境界

Authority要件はRuntimeまたはPluginが登録する型付き`ActivityDefinition`からのみ取得する。

次からAuthority要件を生成しない。

- LLM出力
- ユーザー本文
- viewerの自己申告role
- Prompt内の自然言語
- Moral Profile
- Desire State
- Motivation Appraisal

現在入力の`authority_role`と`instruction_trusted`は既存の入力信頼境界から受け取る。

## 10. 既存Authority判定との関係

本契約は候補間比較用のShadow metadataである。

実行許可の正本は引き続き既存RuntimeのAuthority、Capability、Constraint、Confirmation、Claim Validation、Safety境界とする。

本Versionでは次を行わない。

```text
ActivityAuthorityRequirement
    → Activity Plan拒否
    → Plugin Command拒否
```

将来実適用する場合も、既存の実行直前検証を削除または短絡しない。

## 11. Execution Boundary全体判定

第10工程完了後は、次の状態になり得る。

```text
semantic equivalence: confirmed
authority equivalence: confirmed
capability equivalence: confirmed
constraint equivalence: confirmed
safety equivalence: unconfirmed
```

Safety契約は第11工程で追加するため、Execution Boundary全体は引き続き通常`unconfirmed`となる。

したがって、次を維持する。

```text
activation_permitted = false
```

## 12. 診断ログ

既存Execution Boundary診断へ次を含める。

- Authority同等性状態
- 現在のAuthority role
- instruction trusted状態
- 候補別policy ID
- 候補別allowed roles
- 候補別trusted instruction要否
- 候補別current request authorized
- Authority同等性理由

会話本文、Prompt全文、秘密情報は追加しない。

## 13. テスト方針

次を検証する。

- policy IDとroleの正規化
- 空policy IDを拒否する
- 空role集合を拒否する
- role重複を拒否する
- role順序差だけでは要件差にならない
- 同じAuthority要件は`confirmed`
- 異なるpolicy ID、role集合、trusted instruction要否は`rejected`
- Authority要件未設定候補を含む場合は`unconfirmed`
- 現在入力の許可状態と候補間同等性を混同しない
- Authorityが`confirmed`でもSafetyが未確認なら全体は`unconfirmed`
- `activation_permitted=false`を維持する
- Activity候補順と実選択を変更しない
- 既存Authority、Capability、Constraint、Plugin境界を回帰させない

## 14. 後続工程

第11工程で候補別Safety policy IDとrisk classの正規契約を追加する。

その後、第12工程で次のすべてを満たす場合だけ適用候補になり得る統合条件を設計する。

- 意味的同等性`confirmed`
- Authority同等性`confirmed`
- Capability同等性`confirmed`
- Constraint同等性`confirmed`
- Safety同等性`confirmed`
- pinned候補ではない
- 同一Motivation段階
- Moral Stateが安定域
- 十分なmoral fit差

第10工程では統合条件を有効化しない。
