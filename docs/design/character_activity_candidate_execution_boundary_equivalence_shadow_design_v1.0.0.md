# Activity候補Execution Boundary同等性Shadow設計 v1.0.0

## 1. 目的

MoralによるActivity候補選好を将来限定的に適用するには、意味的に代替可能であるだけでなく、Authority、Capability、Constraint、Safetyの実行境界も候補間で同等であることを確認する必要がある。

本設計では、これら4境界を独立した型付き契約として評価し、既存のMoral候補選好Shadowへ観測結果を追加する。ただし、実際の候補順、Activity選択、実行許可、禁止判定には影響させない。

## 2. 適用範囲

本Versionで追加する範囲は次のとおり。

- Authority同等性Assessment
- Capability同等性Assessment
- Constraint同等性Assessment
- Safety同等性Assessment
- 4境界を集約するExecution Boundary同等性Assessment
- Situation Evaluator応答後のShadow observerによる決定論的評価
- Shadow結果と診断ログへの投影
- 回帰テスト

次は対象外とする。

- Authorityルールの新設または変更
- Capability可用性判定の変更
- Constraint検証器の変更
- Safetyポリシーの新設または変更
- ActivityDefinitionへのAuthority／Safetyメタデータ追加
- Moralによる実候補順の変更
- `activation_permitted`の有効化
- Character Response内容への投影
- DB永続化
- GUI表示

## 3. 基本方針

### 3.1 各境界を独立して評価する

4境界を一つの曖昧な真偽値へ統合しない。各境界は次の状態を持つ。

- `unconfirmed`: 必要な契約または証拠がない
- `confirmed`: 現在利用可能な型付き情報から同等と確認できる
- `rejected`: 現在利用可能な型付き情報から非同等と確認できる

### 3.2 情報不足を同等とみなさない

候補別Authority要件やSafetyポリシー識別子は、現行`ActivityDefinition`に存在しない。このため、本VersionではAuthorityとSafetyを原則`unconfirmed`とする。

同じRuntime経路を通ること、同じユーザー入力を共有すること、同じSafety検証器が後段に存在することだけを理由に`confirmed`にはしない。

### 3.3 既存境界を再実装しない

Shadow評価はAuthority、Capability、Constraint、Safetyの実行判定を代替しない。既存の検証結果を迂回せず、候補間の契約差だけを観測する。

## 4. 型付き契約

### 4.1 AuthorityEquivalenceAssessment

保持する情報:

- status
- authority role
- instruction trusted
- candidate-specific requirement contract availability
- reasons

現行定義には候補別Authority要件がないため、候補数が十分でも`unconfirmed`とする。

### 4.2 CapabilityEquivalenceAssessment

保持する情報:

- status
- 候補別required capability
- 候補別現在可用性
- reasons

すべての候補で`required_capability`が完全一致するとき`confirmed`とする。異なるCapability、Capabilityあり／なしの混在は`rejected`とする。

Capabilityが現在利用可能かどうかも記録するが、可用性が同じだけでは同等とはみなさない。

### 4.3 ConstraintEquivalenceAssessment

保持する情報:

- status
- 候補別schema version
- 候補別schema fingerprint
- reasons

`constraints_schema_version`と、正規化した`constraints_schema`のfingerprintがすべて一致するとき`confirmed`とする。いずれかが異なる場合は`rejected`とする。

Schemaを決定論的に正規化できない場合は`unconfirmed`とする。

### 4.4 SafetyEquivalenceAssessment

保持する情報:

- status
- candidate-specific policy contract availability
- reasons

現行定義には候補別Safetyポリシー識別子がないため、`unconfirmed`とする。

Safety禁止とMoral抑制は別契約のまま維持する。

### 4.5 ExecutionBoundaryEquivalenceAssessment

4境界を保持し、全体statusを次の順序で決める。

1. いずれかが`rejected`なら全体も`rejected`
2. 4境界すべてが`confirmed`なら全体も`confirmed`
3. それ以外は`unconfirmed`

本VersionではAuthorityとSafetyが原則`unconfirmed`のため、通常は全体`confirmed`にならない。これは意図した保守動作である。

## 5. 処理フロー

```text
Situation Evaluator LLM応答
    ↓
高確信度の意味的同等性Evidence
    ↓
SituationSemanticEquivalenceShadowObserver
    ├─ Motivation順位を再計算
    ├─ moral_fitを再計算
    ├─ Moral候補選好Shadowを計算
    └─ candidate_groupをExecution Boundary evaluatorへ渡す
          ├─ Authority: 契約不足のためunconfirmed
          ├─ Capability: required_capabilityを比較
          ├─ Constraint: schema version／fingerprintを比較
          └─ Safety: 契約不足のためunconfirmed
    ↓
MoralActivityCandidatePreferenceShadowへAssessmentを付加
    ↓
診断ログへ記録
```

Execution Boundary評価結果はSituation Evaluator、Behavior Planner、Activity Validatorへ戻さない。

## 6. Candidate group

評価対象はMoral候補選好Shadowが選んだ`candidate_group`と完全に一致させる。

次の場合は全体`unconfirmed`とする。

- candidate groupが2件未満
- candidate groupに重複がある
- 現在のActivityDefinition集合に存在しない候補がある

候補を補完、追加、削除、並べ替えしない。

## 7. Capability比較

例:

```text
A.required_capability = llm.character
B.required_capability = llm.character
→ confirmed
```

```text
A.required_capability = stream.control
B.required_capability = game.control
→ rejected
```

```text
A.required_capability = null
B.required_capability = stream.control
→ rejected
```

現在可用性は`BehaviorPlanningContext.available_capabilities`から記録する。可用性は実行許可ではなく診断情報である。

## 8. Constraint比較

Schema fingerprintは次から生成する。

- schema version
- JSON互換Schemaをkey順で正規化した表現

値の順序に意味がないmappingのkey順差は同一とみなす。一方、配列順、型、required、default、additionalPropertiesなどの差はfingerprint差として扱う。

## 9. Authority／Safetyの保守動作

現行`ActivityDefinition`は、次を候補別の型付き情報として持たない。

- 必要Authority role
- trusted instruction要否
- Safety policy ID
- Safety risk class

このため、本Versionで候補別ルールを推測しない。

将来これらが正規契約へ追加された場合に限り、別Versionで`confirmed`／`rejected`判定を有効化する。

## 10. Shadow結果

`MoralActivityCandidatePreferenceShadow`へ次を追加する。

- `execution_boundary_equivalence`
- `execution_boundary_equivalence_confirmed`

ただし、次は維持する。

```text
activation_permitted = false
```

`static_eligible`、`current_order`、`hypothetical_order`、`preferred_activity_type`の既存計算も変更しない。

## 11. 診断ログ

次を追加記録する。

- execution boundary overall status
- authority status
- capability status
- constraint status
- safety status
- 候補別required capability
- 候補別Capability可用性
- constraint schema version／fingerprint
- 各Assessmentのreason

会話本文、Prompt全文、秘密情報は含めない。

## 12. 失敗時動作

Execution Boundary評価またはShadow observerで例外が発生してもActivity Planningを失敗させない。

- 実候補順は維持
- 実Activity選択は維持
- `activation_permitted=false`を維持
- 警告ログのみ記録

## 13. テスト方針

次を検証する。

- 同じrequired capabilityを持つ候補はCapability `confirmed`
- 異なるrequired capabilityはCapability `rejected`
- 同じConstraint schema version／fingerprintはConstraint `confirmed`
- Schema差はConstraint `rejected`
- Authority契約不足はAuthority `unconfirmed`
- Safety契約不足はSafety `unconfirmed`
- 一境界でも`rejected`なら全体`rejected`
- 未知候補を含む場合は全体`unconfirmed`
- 結果がShadow contextへ投影される
- 意味的同等性がconfirmedでも実選択へ影響しない
- `activation_permitted=false`を維持する
- 既存Authority、Capability、Constraint、Safety境界を回帰させない

## 14. 後続工程

1. ShadowログでCapability／Constraintの非同等率を集計する
2. Authority要件の正規契約が必要か設計する
3. Safety policy ID／risk classの正規契約が必要か設計する
4. 4境界すべてを確認可能になった後、意味的同等性と合わせた適用条件を設計する
5. 誤選択率を評価する
6. 機能フラグ付き限定適用を別Versionで設計する
