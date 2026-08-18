# V2 Semantic Verification Relation Edge Contract

Owner Issue: #363
Live Validation: #427
Supersedes:
- `semantic_verification_contracts.md` の Role B bidirectional support/accounting における Provider二重出力部分
- `semantic_verification_observer_strategy.md` の proposition側とaccounting側へ同一support edgeを重複申告させる部分

Status: Canonical Supplement / Live Validation feedback

## 1. 背景

#427 Render実LLM検証の「雨を伝える②：水滴表現」で、Role Bが同じPlan↔blind unit関係を2か所へ出力した結果、Runtimeで:

`proposition supportとblind unit accountingが一致しません`

が発生した。

旧Provider candidateは同じsupport edgeを:

1. `proposition_observations[].supporting_blind_unit_ids`
2. `blind_unit_accounting[].proposition_ids`

の両方向へLLM自身に重複申告させていた。

これは独立Observer間の照合ではない。同じRole B / 同じProvider response内で同じ関係を二重記述しているだけであり、semantic safetyを実質的に増やさず、構造的不一致のfailure surfaceを増やす。

## 2. Canonical decision

Role B Provider outputにおけるPlan proposition↔blind unit support edgeの唯一の正本は:

`blind_unit_accounting[].proposition_ids`

とする。

### Provider output

`proposition_observations[]`は次だけを出力する。

- proposition_id
- ENTAILED / MISSING / CONTRADICTED / AMBIGUOUS
- polarity / certainty / degree / execution relative relation
- actual utterance evidence

Providerへ`supporting_blind_unit_ids`を重複出力させない。

`blind_unit_accounting[]`はblind unitごとにexactly one recordを持つ。

- `SUPPORTED_BY_PLAN` → proposition_ids 1件以上
- `UNSUPPORTED_EXTRA` → proposition_ids=[]
- `PERMITTED_NON_MATERIAL_STYLE` → proposition_ids=[]
- `AMBIGUOUS` → proposition_ids=[]

## 3. Runtime normalization

RuntimeはProvider result受領後、`blind_unit_accounting`からpropositionごとの`supporting_blind_unit_ids`を決定論的に導出する。

この派生値はRuntime Observer DTOで保持してよいが、Provider自己申告ではない。

```text
Provider blind_unit_accounting
  u1 -> SUPPORTED_BY_PLAN [p1]
  u2 -> SUPPORTED_BY_PLAN [p1, p2]

Runtime derived
  p1.supporting_blind_unit_ids = [u1, u2]
  p2.supporting_blind_unit_ids = [u2]
```

順序はProvider accounting順を保持し、同じblind unit / proposition IDの重複は既存closed validationで拒否する。

## 4. Safety invariants retained

単一正本化は検証を緩めない。

既存Authorityで次を維持する。

- blind unit全件exactly one accounting
- unknown proposition / blind unit拒否
- `SUPPORTED_BY_PLAN`が参照するpropositionは`ENTAILED`でなければならない
- ENTAILED propositionはRuntime導出supportを1件以上持つ
- proposition evidenceは導出support blind unitのevidenceへgroundする
- accounting evidenceは元blind unit evidenceへgroundする
- MATERIAL_SEMANTIC_CONTENTをPERMITTED_NON_MATERIAL_STYLEへ降格禁止
- unsupported / ambiguous material contentはfail-closed
- Character `realization_refs`をsemantic proofにしない

つまり削除するのは**同じLLMの重複自己申告**だけで、Plan↔actual utteranceのgrounding obligationは維持する。

## 5. Provider schema

production `relation_output_schema()`は`proposition_observations[].supporting_blind_unit_ids`を公開しない。

旧test double / branch-local legacy payloadが同fieldを含む場合も、production canonical relation layerはその値をAuthorityとして信用せず、`blind_unit_accounting`から導出した値で上書きする。

real Provider strict Structured Outputでは新schemaにより重複field自体を生成させない。

## 6. V1/V2原則との整合

この変更は以下の既存原則と一致する。

- Provider自己申告をAuthority化しない
- 同じ意味関係の二重正本を持たない
- Runtimeで決定可能な派生値をLLMへ生成させない
- finite自然語matcherを導入しない
- Plan-aware Role Bのsemantic relation観測自体は維持する
- Plan-blind Role Aとの独立性は維持する

## 7. Verification

自動:

- production packageの`SemanticVerifier`がcanonical relation layerを使用する
- Provider schemaに`supporting_blind_unit_ids`が存在しない
- mismatched legacy support自己申告をaccounting由来値で上書きする
- non-SUPPORTED accountingからsupportを生成しない
- existing Authority / evidence / acceptance tests PASS
- Ruff / Mypy strict / full pytest / compileall / diff check

実LLM #427:

1. `雨を伝える②：水滴表現`を再実行
2. `proposition supportとblind unit accountingが一致しません`が消えること
3. Role B semantic relation / evidence / final acceptanceを確認
4. 失敗時もExportしてProvider resultを保存

## 8. Merge Gate

この補修だけで#363をmergeしない。

#427 failure matrix、degree/speech-actを含むfalse accept / false reject評価、#330 final canonical再照合が完了するまでMerge GateはHOLDを維持する。
