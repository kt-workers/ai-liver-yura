# V2 Semantic Verification Relation Edge Contract

Owner Issue: #363
Live Validation: #427
Supersedes:
- `semantic_verification_contracts.md` の Role B bidirectional support/accounting における Provider二重出力部分
- `semantic_verification_observer_strategy.md` の proposition側とaccounting側へ同一support edgeを重複申告させる部分
- 上記2文書に残る `SUPPORTED_BY_PLAN` を `ENTAILED` のみに限定する旧記述

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

さらに#427の実LLM failure matrixで、`unknown_committed` と `execution_completion_fabricated` はactual material unitが既存Plan propositionを明確に**矛盾**しているにもかかわらず、旧Authorityの `SUPPORTED_BY_PLAN = ENTAILED only` 制約により対応edgeを持てず、同じunitが `UNSUPPORTED_EXTRA` へ強制分類された。

これは `UNSUPPORTED_EXTRA = 対応するPlan proposition自体が存在しないmaterial content` という既存canonical定義と矛盾する。

## 2. Canonical decision

Role B Provider outputにおけるPlan proposition↔blind unit grounding edgeの唯一の正本は:

`blind_unit_accounting[].proposition_ids`

とする。

`SUPPORTED_BY_PLAN` の名称に含まれる `supported` は、**Plan propositionとの意味的対応 / grounding** を表す。最終的にその発話が正しい、許可される、acceptされることを意味しない。

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

`SUPPORTED_BY_PLAN`が参照できるPlan proposition relationは:

- `ENTAILED`
- `CONTRADICTED`

とする。

`MISSING`はactual support unitを持たない。`AMBIGUOUS`は対応関係自体を安全に確定できないため、`SUPPORTED_BY_PLAN`へ閉じずfail-closedする。

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

単一正本化とCONTRADICTED groundingは検証を緩めない。

Authorityで次を維持する。

- blind unit全件exactly one accounting
- unknown proposition / blind unit拒否
- `SUPPORTED_BY_PLAN`が参照するproposition relationは `ENTAILED` または `CONTRADICTED`
- ENTAILED propositionはRuntime導出supportを1件以上持つ
- actual evidenceを伴うCONTRADICTED propositionも、対応Plan propositionが存在するならRuntime導出supportを1件以上持つ
- ENTAILED / CONTRADICTED proposition evidenceは導出support blind unitのevidenceへgroundする
- accounting evidenceは元blind unit evidenceへgroundする
- MATERIAL_SEMANTIC_CONTENTをPERMITTED_NON_MATERIAL_STYLEへ降格禁止
- unsupported / ambiguous material contentはfail-closed
- Character `realization_refs`をsemantic proofにしない

つまりsupport edgeは「一致している」という判定ではなく、**どのPlan propositionとactual unitを比較した結果なのか**を保持するgrounding edgeである。

### 4.1 Support edgeとproposition dispositionは別軸

`SUPPORTED_BY_PLAN` の `supported` は「発話内容がPlan内のpropositionと意味的に対応している」という **relation/accounting上のgrounding** を意味し、「発話してよい」「許可されている」というpolicy判定を意味しない。

したがってPlan propositionのdispositionが `FORBIDDEN` であっても、actual utteranceがその禁止命題を実際に表現している場合は:

- proposition relation = `ENTAILED`
- 対応blind unit accounting = `SUPPORTED_BY_PLAN [forbidden proposition id]`

とする。

その後Runtime Acceptanceがproposition dispositionを見て `FORBIDDEN_PROPOSITION_REALIZED` を導出する。

禁止命題を実現したblind unitを、`FORBIDDEN`だからという理由だけで`UNSUPPORTED_EXTRA`へ分類してはならない。`UNSUPPORTED_EXTRA`は**対応するPlan proposition自体が存在しないmaterial content**に使用する。

```text
Plan:
  p1 REQUIRED rain=true
  p2 FORBIDDEN strong_wind=true

Actual:
  "今日は雨だよ。風も強いよ。"

Role B:
  p1 -> ENTAILED
  p2 -> ENTAILED
  rain unit -> SUPPORTED_BY_PLAN [p1]
  wind unit -> SUPPORTED_BY_PLAN [p2]

Runtime Acceptance:
  FORBIDDEN_PROPOSITION_REALIZED
```

### 4.2 Contradictionとunsupportednessは別軸

actual unitが既存Plan propositionと同じsemantic subject / propositionについて**反対・不整合な内容を述べている**場合、そのunitはPlan外ではない。

この場合:

- proposition relation = `CONTRADICTED`
- 対応blind unit = `SUPPORTED_BY_PLAN [that proposition id]`
- Runtime Acceptance = `PROPOSITION_CONTRADICTED`

とする。

同じunitを `UNSUPPORTED_EXTRA` にも分類してはいけない。`PROPOSITION_CONTRADICTED` と `UNSUPPORTED_EXTRA_CLAIM` の二重rejectは、別のPlan外material contentが実際に存在するときだけ成立する。

例:

```text
Plan:
  p1 museum.open_status = unknown

Actual:
  "博物館は今日は開いてるよ。"

Role B:
  p1 -> CONTRADICTED
  polarity_relation -> UNKNOWN_COMMITTED
  certainty_relation -> STRENGTHENED
  utterance unit -> SUPPORTED_BY_PLAN [p1]

Runtime Acceptance:
  PROPOSITION_CONTRADICTED
```

```text
Plan:
  p1 execution.status = requested

Actual:
  "その操作はもう完了したよ。"

Role B:
  p1 -> CONTRADICTED
  execution_relation -> CONTRADICTED
  utterance unit -> SUPPORTED_BY_PLAN [p1]

Runtime Acceptance:
  PROPOSITION_CONTRADICTED
```

この変更は矛盾発話を許可するものではない。むしろ、**何に矛盾したのかというgroundingを保持したまま、正しいreject categoryへ到達する**ための責務分離である。

## 5. Provider schema

production `relation_output_schema()`は`proposition_observations[].supporting_blind_unit_ids`を公開しない。

旧test double / branch-local legacy payloadが同fieldを含む場合も、production canonical relation layerはその値をAuthorityとして信用せず、`blind_unit_accounting`から導出した値で上書きする。

real Provider strict Structured Outputでは新schemaにより重複field自体を生成させない。

## 6. Cross-field inconsistency failure policy

単一正本化後も、Role Bはproposition relationとblind-unit accountingという異なる観測事実を返すため、次のようなcross-field不整合は起こり得る。

- propositionは`ENTAILED`だが、accountingから導出できるsupport blind unitが0件
- actual evidenceを伴う`CONTRADICTED` propositionだが、対応Plan grounding edgeが0件
- proposition evidenceが導出supportへgroundしない
- `SUPPORTED_BY_PLAN` accountingが`MISSING` / `AMBIGUOUS` propositionを参照する

これらはactual utteranceを受理してよいことを意味しない。Provider candidateがproduction Domain contractを満たしていないため、**commitせずfail-closed**する。

ただしDomain `ValueError`をHTTP 400等へ生で漏らしてはならない。production `SemanticVerifier`は、既存`SemanticVerificationError`を除くcandidate parse / Authority contract `ValueError`を `SCHEMA_INVALID` へ正規化する。

これにより:

- invalid Provider candidateはObservation / Acceptanceをcommitしない
- callerはstructured failure codeを受け取れる
- transport/UI固有のHTTP例外へ意味契約違反を混ぜない
- failureをfixed phrase / regex / fallback判定で受理へ変えない

## 7. V1/V2原則との整合

この変更は以下の既存原則と一致する。

- Provider自己申告をAuthority化しない
- 同じ意味関係の二重正本を持たない
- Runtimeで決定可能な派生値をLLMへ生成させない
- invalid Provider candidateはcommitしない
- finite自然語matcherを導入しない
- Plan-aware Role Bのsemantic relation観測自体は維持する
- Plan-blind Role Aとの独立性は維持する
- contradictionとunsupportednessを混同しない

## 8. Validation fixture separation

「同じ意味を別表現で保持できるか」を測るcaseへ、継続時間・強度・程度など別facetを混ぜない。

雨の`raining=true`だけを比較するbaseline variationでは、`ずっと`や`落ち続けている`のようにduration/degreeへ解釈し得る表現を除く。degree validationはdegreeを明示した専用caseで別途行う。

shared-stance確認も同様に、semantic contentを固定したままinteraction actだけを変える。

failure matrixの単一要因caseも同じ原則で構成する。特に`forbidden_realized`はself-disclosure / new-direction等を混ぜず、同一topic内のexternal FORBIDDEN propositionを実現して、`FORBIDDEN_PROPOSITION_REALIZED`だけを観測できるfixtureを優先する。

`question_budget_exceeded`のように1つの追加material unitが同時にDIRECTED_QUESTIONであるcaseは、Plan外material contentとquestion budgetという**本当に別の意味軸**が同時成立し得る。この場合の複数reject categoryはdiagnostic duplicationではなくmulti-axis observationとして扱う。

## 9. Verification

自動:

- production packageの`SemanticVerifier`がcanonical relation layerを使用する
- Provider schemaに`supporting_blind_unit_ids`が存在しない
- mismatched legacy support自己申告をaccounting由来値で上書きする
- non-SUPPORTED accountingからsupportを生成しない
- `FORBIDDEN` propositionの実現もsemantic grounding edgeを持ち、permissionとsupportを混同しないPrompt契約
- `CONTRADICTED` propositionも対応Plan grounding edgeを持ち、unsupportednessとcontradictionを混同しない
- ENTAILED / CONTRADICTED evidenceがgrounding unit evidenceへbindされる
- candidate/Authority contract `ValueError`が`SCHEMA_INVALID`へ正規化される
- existing Authority / evidence / acceptance tests PASS
- Ruff / Mypy strict / full pytest / compileall / diff check

実LLM #427:

1. `unknown_committed` を再実行し、p1=CONTRADICTED + unit=SUPPORTED_BY_PLAN [p1] + final `PROPOSITION_CONTRADICTED` を確認
2. `execution_completion_fabricated` を再実行し、p1=CONTRADICTED + unit=SUPPORTED_BY_PLAN [p1] + final `PROPOSITION_CONTRADICTED` を確認
3. `question_budget_exceeded` は既存実LLM証跡をmulti-axis PASSとして保持する
4. 失敗時もExportしてfailure code / resultを保存

## 10. Merge Gate

この補修だけで#363をmergeしない。

#427 live rerun、#330 final canonical再照合が完了するまでMerge GateはHOLDを維持する。
