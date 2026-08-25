# V2 Semantic Verification Relation Edge Contract

Owner Issue: #363
Live Validation: #427 / #434
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

### 1.1 #434 current Character Language実測で判明した追加failure surface

2026-08-19、#434 Character Language LabのIsolation実LLM検証で、同一actual utterance:

`今日は少し涼しいね。`

に対し3/3回、Role A / Role B Provider call自体は成功したにもかかわらず、#363 production Authorityで:

`schema_invalid / Semantic Verification candidate contract invalid: proposition evidenceはsupporting blind unitへgroundする必要があります`

となった。

原因はRole Bが`proposition_observations[].evidence_refs`を独自に再生成し、Role Aで先に確定済みのblind unit evidenceとquote粒度が一致しなかったことである。

- actual utteranceへのgrounding自体は両方成立し得る
- しかしRuntime契約はproposition evidenceをsupporting blind unit evidenceへexact keyでgroundする
- Provider JSON Schemaではこのcross-field subset制約を表現できない
- Promptで同じquoteを再生成させるだけでは、同じ構造的不一致面を残す

よってsupport edgeと同様に、Runtimeで決定可能なproposition evidenceをProviderへ二重生成させない。

## 2. Canonical decision

Role B Provider outputにおけるPlan proposition↔blind unit support edgeの唯一の正本は:

`blind_unit_accounting[].proposition_ids`

とする。

さらにproposition semantic groundingに使用するevidenceの唯一の正本は:

`BlindUtteranceObservation.units[].evidence_refs`

とする。

### Provider output

`proposition_observations[]`は次だけを出力する。

- proposition_id
- ENTAILED / MISSING / CONTRADICTED / AMBIGUOUS
- polarity / certainty / degree / execution relative relation

Providerへ次を重複出力させない。

- `supporting_blind_unit_ids`
- `evidence_refs`

`blind_unit_accounting[]`はblind unitごとにexactly one recordを持つ。

- `SUPPORTED_BY_PLAN` → proposition_ids 1件以上
- `UNSUPPORTED_EXTRA` → proposition_ids=[]
- `PERMITTED_NON_MATERIAL_STYLE` → proposition_ids=[]
- `AMBIGUOUS` → proposition_ids=[]

Role Bは「どのblind unitがどのPlan propositionへ対応するか」というsemantic relation/accountingを判断する。actual quote evidenceそのものはRole Aで既に確定済みなので再生成しない。

## 3. Runtime normalization

RuntimeはProvider result受領後、`blind_unit_accounting`からpropositionごとの`supporting_blind_unit_ids`を決定論的に導出する。

そのsupporting blind unit IDsから、Role Aで確定済みの`BlindUtteranceObservation.units[].evidence_refs`を順序保持で集約し、propositionの`evidence_refs`を決定論的に導出する。

これらの派生値はRuntime Observer DTOで保持してよいが、Provider自己申告ではない。

```text
Role A fixed blind observation:
  u1.evidence = [e1]
  u2.evidence = [e2, e3]

Role B provider accounting:
  u1 -> SUPPORTED_BY_PLAN [p1]
  u2 -> SUPPORTED_BY_PLAN [p1, p2]

Runtime derived:
  p1.supporting_blind_unit_ids = [u1, u2]
  p1.evidence_refs = [e1, e2, e3]
  p2.supporting_blind_unit_ids = [u2]
  p2.evidence_refs = [e2, e3]
```

導出規則:

- support順はProvider accounting順
- evidence順はsupport順→各blind unit内evidence順
-同一evidence key `(segment_id, quote, occurrence_index)` は最初の1件だけ保持する
- non-SUPPORTED accountingはproposition support/evidenceを生成しない
- MISSING / AMBIGUOUS propositionはsupportを持てず、従ってderived evidenceも空

## 4. Safety invariants retained

単一正本化は検証を緩めない。

既存Authorityで次を維持する。

- blind unit全件exactly one accounting
- unknown proposition / blind unit拒否
- `SUPPORTED_BY_PLAN`が参照するpropositionは`ENTAILED`または`CONTRADICTED`でなければならない
- ENTAILED / CONTRADICTED propositionはRuntime導出supportを1件以上持つ
- proposition evidenceはRuntime導出support blind unitの確定済みevidenceだけから生成する
- accounting evidenceは元blind unit evidenceへgroundする
- MATERIAL_SEMANTIC_CONTENTをPERMITTED_NON_MATERIAL_STYLEへ降格禁止
- unsupported / ambiguous material contentはfail-closed
- Character `realization_refs`をsemantic proofにしない

削除するのは**LLMの重複自己申告**だけで、Plan↔actual utteranceのgrounding obligationは維持する。

Role Bがsupporting blind unitを誤って選べば、semantic relation/accountingとしてRuntime AcceptanceまたはAuthorityで引き続きreject対象になる。evidenceをRuntime導出することは、誤ったsemantic supportを正しいものへ補正するfallbackではない。

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

これによりsupport edgeはsemantic grounding、dispositionはspeech policyという責務分離を維持する。

## 5. Provider schema

production `relation_output_schema()`は`proposition_observations[]`に次を公開しない。

- `supporting_blind_unit_ids`
- `evidence_refs`

旧test double / branch-local legacy payloadが同fieldを含む場合も、production canonical relation layerはその値をAuthorityとして信用しない。

- support IDsは`blind_unit_accounting`から上書き導出
- proposition evidenceはrelation request内のfixed `blind_observation`から上書き導出

real Provider strict Structured Outputではproduction schemaにより両field自体を生成させない。

## 6. Cross-field inconsistency failure policy

単一正本化後も、Role Bはproposition relationとblind-unit accountingという異なる観測事実を返すため、次のcross-field不整合は残る。

- propositionは`ENTAILED` / `CONTRADICTED`だが、accountingから導出できるsupport blind unitが0件
- `SUPPORTED_BY_PLAN` accountingが`ENTAILED` / `CONTRADICTED`でないpropositionを参照する
- unknown proposition / blind unitをaccountingが参照する

これらはactual utteranceを受理してよいことを意味しない。Provider candidateがproduction Domain contractを満たしていないため、**commitせずfail-closed**する。

一方、Role Bがproposition evidence quoteをRole Aと別粒度で再生成しただけの不一致は、Providerからその重複field自体を除去することでfailure surfaceから消す。

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
- Role AのPlan-blind evidenceをRole Bが勝手に別quoteへ置換しない
- invalid Provider candidateはcommitしない
- finite自然語matcherを導入しない
- Plan-aware Role Bのsemantic relation観測自体は維持する
- Plan-blind Role Aとの独立性は維持する

## 8. Validation fixture separation

「同じ意味を別表現で保持できるか」を測るcaseへ、継続時間・強度・程度など別facetを混ぜない。

雨の`raining=true`だけを比較するbaseline variationでは、`ずっと`や`落ち続けている`のようにduration/degreeへ解釈し得る表現を除く。degree validationはdegreeを明示した専用caseで別途行う。

shared-stance確認も同様に、semantic contentを固定したままinteraction actだけを変える。

failure matrixの単一要因caseも同じ原則で構成する。特に`forbidden_realized`はself-disclosure / new-direction等を混ぜず、同一topic内のexternal FORBIDDEN propositionを実現して、`FORBIDDEN_PROPOSITION_REALIZED`だけを観測できるfixtureを優先する。

## 9. Verification

自動:

- production packageの`SemanticVerifier`がcanonical relation layerを使用する
- Provider schemaに`supporting_blind_unit_ids` / proposition `evidence_refs`が存在しない
- mismatched legacy support自己申告をaccounting由来値で上書きする
- mismatched legacy proposition evidence自己申告をfixed blind evidence由来値で上書きする
- non-SUPPORTED accountingからsupport/evidenceを生成しない
-複数support blind unitのevidenceを順序保持・dedupeして導出する
- `FORBIDDEN` propositionの実現もsemantic support edgeを持ち、permissionとsupportを混同しないPrompt契約
- candidate/Authority contract `ValueError`が`SCHEMA_INVALID`へ正規化される
- existing Authority / evidence / acceptance tests PASS
- Ruff / Mypy strict / full pytest / compileall / diff check

実LLM #434:

1. `Neutral fact / direct answer` / `今日は少し涼しいね。` を同条件で3回再実行
2. Role A evidenceとRuntime-derived proposition evidenceを確認
3. 3/3が旧`proposition evidenceはsupporting blind unitへground` schema failureを再発しないことを確認
4. semantic acceptance / rejectionは通常の#363 closed policyで評価する
5. ExportにProvider result / failure code / latencyを保持する

必要に応じて#427 standalone Labでもrelation-edge regressionを再実行する。

## 10. Merge Gate

この補修だけで#363をmergeしない。

#434 actual current Character Language→#363 e2e、model/reasoning policy、latency/non-blocking、#330 final Human quality等の残存Merge Gateを満たすまでHOLDを維持する。
