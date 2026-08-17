# V2 Semantic Verification Observer / Live Validation Strategy

Owner Issue: #363
Validation Work: #427
Parent: #325
Upstream: #362 / #330
Provider: #357
Related: #348 / #352
Status: Detailed Design Reconciliation / Implementation-to-Live-Validation Gate

## 1. 目的

この文書は `semantic_verification_contracts.md` のうち **open-ended natural-language semantic observation方式とLive Validation Gate** を補足し、V1 #288 / #293 / #303で確認した失敗をV2へ持ち込まないための正本supplementである。

V1では次の両側で問題が出た。

1. blind extraction / speech→元semantic enum再構成
   - medium/low certainty、unknown、degree、concept等でfalse reject
   - schema負荷が高い
2. Plan-aware verification
   - expected facetへObserverがanchoringしfalse acceptし得る

したがってV2では、どちらか一方を万能なsemantic proofとして採用しない。
finite word / phrase / regex / substring / synonym / antonym listをsemantic authorityへ戻さない。

---

## 2. 前提: 自由自然言語の意味保持に完全な決定論的proofはない

#330がopen-ended LLMで自由な`CharacterUtterance`を生成する限り、Runtimeだけで自然言語意味を完全証明することはできない。

設計目標は次とする。

- semantic uncertaintyを隠さない
- 1種類のObserverの自己一致をPASS根拠にしない
- open-ended意味を有限候補へ閉じ込めない
- Planを見ない観測でmaterial claim inventoryを先に固定する
- Plan-aware観測は、その独立inventoryを消したり作り替えたりできない
- disagreement / ambiguityはfail-closed
- 実LLM false accept / false rejectを早期計測しMerge Gateへ使う

LLMは観測candidateを返し、最終acceptanceはRuntime closed policyが所有する。

---

## 3. Production verification topology

初期productionは**品質優先の2-stage observer**とする。

```text
SpeechSemanticPlan + CharacterUtterance
        ↓
0. Deterministic Pair / Provenance Gate
        ↓
A. Blind Utterance Inventory Observer
   input = utterance only
   Plan / realization_refs非提示
        ↓
   immutable BlindUtteranceObservation
        ↓
B. Plan Relation Observer
   input = Plan + utterance + frozen blind units
        ↓
   PlanRelationObservationCandidate
        ↓
C. Runtime deterministic reconciliation
        ├─ proposition fidelity
        ├─ blind unit accounting
        ├─ unsupported extra
        ├─ actual speech-act budget
        └─ optional closed-facet counterfactual probes
        ↓
SemanticRelationObservation
        ↓
Runtime Closed Acceptance
```

A→Bはsemantic verification内部ではdata dependencyを持つ。
**初期版ではここを無理に並列化しない。**

理由:

- AがPlanを知らない状態でmaterial unitを固定する必要がある
- BがAのunitを1件ずつ説明し、Plan-aware anchoringでclaim自体を消す余地を減らす
- 完全並列A/BではBがAの独立unitを知らず、Plan外claimの対応付けが弱くなる

ただしA/B await中も:

- current speech playback
- Body realtime
- unrelated input / Activity
- #331 Speech Performance
- #348 policyで許可されたspeculative TTS preparation

は停止させない。

quality / latencyを#427で実測後、semantic contractを維持できる場合にのみbatch/fused/parallel optimizationを検討する。

---

## 4. Logical LLM Roles

#363 Moduleは2つのlogical Roleを所有する。

### Role A

```text
role_id: semantic_verification_blind_inventory
input_schema_id: semantic.verification.blind.context.v1
output_schema_id: semantic.verification.blind.candidate.v1
```

### Role B

```text
role_id: semantic_verification_plan_relation
input_schema_id: semantic.verification.relation.context.v1
output_schema_id: semantic.verification.relation.candidate.v1
```

Role A/Bは#323の可変Role contractと#357 production `LLMRolePort`を利用する。

- Provider SDK型をDomainへ出さない
- strict Structured Output
- roleごとにmodel / reasoning policyを独立設定可能
- Role数を固定system invariantにしない
- A/Bが同Providerを共有してもlogical responsibilityは混ぜない

contrastive probeは初期版ではB request内の補助input/outputとして扱い、第三の常時LLM Roleを追加しない。

---

## 5. Stage 0 — Deterministic Pair / Provenance Gate

LLM呼出前にRuntimeだけで確認する。

- committed `SpeechSemanticPlan`
- committed `CharacterUtterance`
- exact plan / utterance / decision / intent / event identity
- source / goal / attention revision
- current eligibility
- superseded / cancelled
- strict DTO / enum / bounded size

`CharacterUtterance.realization_refs`は構造hintとして存在しても、Role A/Bのsemantic proofへ渡さない。

このGateで失敗したpairをsemantic LLMへ送らない。

---

## 6. Role A — Blind Utterance Inventory Observer

### 6.1 目的

Planを見せずactual utterance内の**material semantic units**を観測し、Plan anchoringでextra claimが消えることを防ぐ。

Aは元`SpeechSemanticPlan`を再構築しない。
polarity / certainty / degree等をPlan schemaへround-tripすることも要求しない。

### 6.2 入力

- actual `CharacterUtterance.segments[].text`
- segment identity
- request / trace identity

渡さないもの:

- SpeechSemanticPlan
- expected proposition ID
- expected polarity / certainty / degree / execution state
- Character `realization_refs`
- Character candidate自己申告budget
- raw user text
- raw internal state
- raw execution payload

### 6.3 出力

```text
BlindUtteranceObservationCandidate
- candidate_id
- request_id
- utterance_id
- units[]

BlindSemanticUnit
- unit_id
- kind
- evidence_refs[]
```

初期closed `kind`:

- `MATERIAL_CLAIM`
- `DIRECTED_QUESTION`
- `NEW_DIRECTION`
- `NON_PROPOSITIONAL_STYLE`
- `AMBIGUOUS`

Aの目的はpredicate/value/facetを完全抽出することではない。
まず**発話中に独立して説明責任を持つsemantic unitがどこにあるか**をPlan非依存で固定する。

必要な場合のみbounded diagnostic glossを研究表示用に持てるが、Runtime acceptance Authorityにしない。

### 6.4 Evidence

```text
UtteranceEvidenceRef
- segment_id
- quote
- occurrence_index
```

Runtimeはexact quoteの位置だけを検証する。
quote内単語からpolarity/certainty/degree/claim kindを再判定しない。

### 6.5 Role A commit

strict schema / identity / evidence grounding成功後、#363 Authorityがimmutable `BlindUtteranceObservation`を構築する。

Provider candidateをそのままB入力の正本にしない。

---

## 7. Role B — Plan Relation Observer

### 7.1 目的

Aで固定済みのblind unitを保持したまま、Plan propositionとの意味関係を観測する。

Bは「PASSか」を答えない。

### 7.2 入力

- typed `SpeechSemanticPlan`
- actual `CharacterUtterance.segments[].text`
- immutable `BlindUtteranceObservation`
- exact pair identity
- relation enum definition
- optional request-local closed-facet probe set

BはAのunitを:

- 削除
- 結合して消去
- unit_idを変更
- `NON_PROPOSITIONAL_STYLE`へ勝手に再分類

できない。
Bは**各blind unitがPlan上どう説明されるか**を返す。

渡さない/信用しないもの:

- Character `realization_refs`をsemantic proofとして利用
- Character budget自己申告をactual speech proofとして利用
- Provider自身の`accepted/pass/score`
- fixed natural-language answer list

### 7.3 Plan proposition relation

```text
PropositionRelation
- proposition_id
- relation: ENTAILED | MISSING | CONTRADICTED | AMBIGUOUS
- polarity_relation
- certainty_relation
- degree_relation
- execution_relation
- evidence_refs[]
- supporting_blind_unit_ids[]
```

closed facet relation例:

- polarity: `PRESERVED / REVERSED / UNKNOWN_COMMITTED / AMBIGUOUS / NOT_APPLICABLE`
- certainty: `PRESERVED / STRENGTHENED / WEAKENED / AMBIGUOUS / NOT_APPLICABLE`
- degree: `PRESERVED / STRENGTHENED / WEAKENED / OMITTED / ADDED / AMBIGUOUS / NOT_APPLICABLE`
- execution: `PRESERVED / STRENGTHENED / WEAKENED / CONTRADICTED / AMBIGUOUS / NOT_APPLICABLE`

speechからPlan DTO全体を再構築しない。

### 7.4 Blind unit accounting

BはAの各unitについてexactly one accounting recordを返す。

```text
BlindUnitAccounting
- blind_unit_id
- relation
- proposition_ids[]
- evidence_refs[]
```

relation:

- `SUPPORTED_BY_PLAN`
- `UNSUPPORTED_EXTRA`
- `PERMITTED_NON_PROPOSITIONAL_STYLE`
- `QUESTION_OR_DIRECTION`
- `AMBIGUOUS`

Aが`MATERIAL_CLAIM`としたunitをBが`PERMITTED_NON_PROPOSITIONAL_STYLE`へ無条件降格することは禁止。
その組み合わせはRuntimeでschema/policy conflictとしてrejectする。

### 7.5 Budget / self-disclosure

actual utteranceから:

- directed question count
- new-direction count
- self-disclosure relation

を観測する。
Character候補の自己申告値をAuthorityにしない。

---

## 8. Closed-facet Counterfactual Probe — supplemental only

contrastive probeはAcceptance completenessの根拠にしない。

生成責務:

- `SemanticProbeSetBuilder`（#363 deterministic helper）
- Stage 0 snapshot確定後
- Planのclosed facetからrequest-localに生成

固定してよいもの:

- relation algebra
- Planが既に持つclosed facet

生成例:

- polarity preserved vs reversed
- certainty preserved vs strengthened/weakened
- degree preserved vs strengthened/weakened/omitted
- execution preserved vs completion-strengthening/contradiction

禁止:

- semantic content dictionary
- synonym/antonym list
- predicate/value replacement library
- 「猫→犬」等content-specific fixed candidate
- natural-language phrase candidate library

probe IDはopaque / request-localとする。
候補順序はdeterministically seeded shuffle等で位置biasを固定しない。

probe結果と通常relationが矛盾した場合、投票多数決でPASSへ寄せず`AMBIGUOUS / OBSERVER_DISAGREEMENT`とする。

---

## 9. Runtime Reconciliation

Role A/Bのcandidateはstrict parse / identity / evidence grounding後にimmutable observer factへcommitする。

最終`SemanticRelationObservation`は:

- pair identity
- BlindUtteranceObservation ID
- PlanRelationObservation ID
- proposition relations
- blind unit accounting
- budget observation
- optional probe result

へbindする。

### 9.1 REQUIRED

- B relation = ENTAILED
- valid evidence
- supporting blind unitあり
- closed facetにreject relationなし

### 9.2 OPTIONAL

- MISSINGは許容
- 実現した場合はREQUIREDと同じfidelity条件

### 9.3 FORBIDDEN

- ENTAILED / AMBIGUOUSならreject

### 9.4 Blind material unit

A `MATERIAL_CLAIM`はBで:

- `SUPPORTED_BY_PLAN`

でなければacceptしない。

`UNSUPPORTED_EXTRA / AMBIGUOUS`はreject。
`PERMITTED_NON_PROPOSITIONAL_STYLE`への降格もreject。

### 9.5 Question / direction

A/B observationのtyped unit/countとPlan budgetをRuntimeが決定論的比較する。

### 9.6 Observer disagreement

以下は初期policyでreject。

- A unitがB accountingから欠落
- unknown/duplicate blind unit ID
- A material claimをBがstyleへ降格
- A/B evidence identity不整合
- proposition relationとblind accountingが矛盾
- counterfactual probeとrelationが矛盾
- A/BどちらかがAMBIGUOUS

Lab側だけでこのpolicyを緩めない。

---

## 10. Why this differs from V1 failures

### V1 blind round-tripとの違い

AはPlan DTOを再構築しない。
Aはmaterial semantic unit inventoryだけをPlan非依存で固定する。

### V1 Plan anchoringとの違い

BがPlanを見ても、Aが先に固定したmaterial unitsを消せない。
全unitへaccounting obligationを課すため、Plan外claimを「見なかったこと」にしにくい。

### V1 finite lexical guardとの違い

Runtimeは自然語の単語から意味relationを推定しない。
exact quote matchingはevidence位置groundingだけ。

### LLM自己採点との違い

A/B/probeのどれにもfinal PASS Authorityを与えない。
Runtimeがclosed policyからACCEPT/REJECTを導出する。

---

## 11. Failure / retry policy

- Role A schema/provider failure → acceptance生成なし
- Role A ambiguity → fail-closed
- Role B schema/provider failure → acceptance生成なし
- Role B ambiguity/disagreement → reject
- stale / superseded / cancelled during A → Bを開始しない
- stale / superseded / cancelled during B → Observation/Acceptanceをcommitしない

regeneration / retryは#348 Speech preparation policyがboundedに制御する。
#363はreplacement utteranceを生成しない。

Provider unavailable時にfixed sentence / regex / Character自己申告へfallbackしてACCEPTしない。

---

## 12. Concurrency / latency policy

A→Bはsemantic safety上のdata dependencyであり、初期productionでは2 LLM callsを許容する。

これはSystem全体のblocking chainを意味しない。

```text
Verifier A running
while Body/current playback/Performance may continue
        ↓
Verifier B running
while Body/current playback/Performance/safe TTS prep may continue
        ↓
ACCEPTED before external Presentation commit
```

#427で:

- A latency
- B latency
- total verification latency
- TTS/Performance overlap
- false accept/false reject

を同時測定する。

品質が成立してからのみ:

- model軽量化
- A/B shared-provider batching
- fused provider call（blind independenceを失わない方法がある場合のみ）
- selective deterministic proof path

を検討する。

「遅いからPlanをAへ渡す」「遅いからAを削除する」はDesign Gateなしに行わない。

---

## 13. Remaining uncertainty

この方式も数学的semantic proofではない。
A/Bが同Provider/model familyならcorrelated errorは残り得る。

そのため実LLM比較対象:

- same model A/B
- A軽量 + B高精度
- A/B別model class
- reasoning effort差
- repeated runs

を#427で測る。

上位modelだけPASSし軽量baselineが崩れる場合、modelを上げるだけで解決扱いにせずcontract/prompt負荷を再評価する。

---

## 14. #427 Render Live Validation

#427はproduction contractをそのまま呼ぶ。
Lab独自semantic authorityは持たない。

表示:

- Plan
- Utterance
- Stage 0 gate
- Role A blind units
- Role B proposition relations
- Role B blind-unit accounting
- optional probe result
- Runtime reconciliation
- SemanticRelationObservation
- SemanticAcceptance / rejection categories
- A/B/total latency
- token usage
- provider/schema/stale/cancel failure

Shadow diagnosticsは比較研究用に持てるがproduction acceptanceへ混ぜない。

---

## 15. V1 failure matrix

最低限:

- exact preservation
- unseen paraphrase
- required missing
- forbidden realized
- polarity reversal
- unknown→affirm / negate
- certainty strengthen / weaken
- degree strengthen / weaken / omit
- execution completion fabrication
- unsupported extra fact / experience / capability
- optional omission / partial realization
- Plan anchoring trap
- blind extraction trap
- multiple material claims in one sentence
- overlapping proposition realization
- incorrect Character realization_refs
- question/new-direction budget

同じsemantic caseへ複数の自然言語variationを持たせる。
fixture wordingをproduction matcherへ追加してPASSさせることは禁止。

---

## 16. Gate policy

### Design Gate A — PASS_FOR_IMPLEMENTATION_TO_LIVE_VALIDATION

以下が確定したためproduction branch実装を許可できる。

- Stage 0 deterministic pair gate
- Role A blind inventory
- immutable blind observation
- Role B plan relation + blind unit accounting
- Runtime reconciliation
- finite lexical authority禁止
- Provider final PASS禁止
- strict evidence grounding
- stale/supersede/cancel gate
- #427 Live Validation計画

これは**Merge PASSではない**。

### Implementation Gate

- production #363 Module Unit/Adjacent PASS
- strict schema tests
- fake A/B Provider tests
- no finite lexical semantic authority scan PASS
- stale/cancel/supersede tests
- current-head deterministic CI PASS

### Live Validation Gate

Render #427でV1 failure matrixを実LLM実行する。

初回baselineでは都合のよいthresholdを後付けしない。
false accept / false reject / ambiguity / provider failureをcase単位で記録する。

### Merge Gate

次を満たすまで#363 product PRはDraft/未merge。

- V1既知failure classの重大false acceptが解消
- unseen paraphraseで系統的false rejectが残らない
- Plan anchoring trap / blind extraction trapの両方評価済み
- unsupported extra claim見逃しがacceptance基盤として残らない
- A/B disagreement policyが実測で妥当
- model / reasoning policy記録済み
- latencyが観測され、System non-blocking invariantを壊していない
- #330 final canonicalと再照合済み

数値thresholdが必要ならbaseline実測後に#363 canonicalへ明示し、Labだけで変更しない。

---

## 17. Early implementation dependency

#330 PR #423はVerification中でtrunk未統合。

#363 Module単体の早期実LLM検証は:

- production `SpeechSemanticPlan`
- fixture/manual `CharacterUtterance`

で先行可能。

実Character LLM→#363 end-to-endは#330 final canonical再照合後に追加する。

#357 OpenAI Responses Adapterはtrunkへ統合済みなので、#427はproduction `LLMRolePort`から実OpenAIへ接続する。

#363 implementationを#330 current reviewed headへstackする場合はbase SHAを明示し、#330変更時に再照合する。
#363を別の重複implementation lineageで作らない。

---

## 18. Design decision

V2 Semantic Verificationは初期productionで次を採用する。

> **Plan-blind material inventory → Plan-aware per-unit relation/accounting → closed-facet supplemental probes → deterministic fail-closed reconciliation → early real-LLM Render validation**

固定候補集合を意味完全性の根拠にしない。

自由自然言語を維持する以上残るsemantic uncertaintyは隠さず、#427の継続的な実LLM観測をMerge Gateへ組み込む。
