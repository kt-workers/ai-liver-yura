# V2 Semantic Verification Observer / Live Validation Strategy

Owner Issue: #363
Validation Work: #427
Parent: #325
Upstream: #362 / #330
Provider: #357
Related: #348 / #352
Status: Detailed Design Reconciliation / Implementation-to-Live-Validation Gate

## 1. 目的

この文書は、`semantic_verification_contracts.md` のうち **open-ended natural-language semantic observation方式とLive Validation Gate** を補足し、V1 #288 / #293 / #303で確認した失敗をV2へ持ち込まないための正本supplementである。

V1では次の両側で問題が出た。

1. blind extraction / speech→元semantic enum再構成
   - medium/low certainty、unknown、degree、concept等でfalse reject
   - schema負荷が高い
2. Plan-aware verification
   - expected facetへObserverがanchoringしfalse acceptし得る

したがってV2では、どちらか一方を万能なsemantic proofとして採用しない。

また、finite word / phrase / regex / substring / synonym / antonym listをsemantic authorityへ戻さない。

---

## 2. 前提: 自由自然言語の意味保持に完全な決定論的proofはない

#330がopen-ended LLMで自由なCharacterUtteranceを生成する限り、Runtimeだけで自然言語意味を完全証明することはできない。

そのため設計目標を次へ置く。

- LLMのsemantic uncertainty自体を隠さない
- 1種類のObserverの自己一致をPASS根拠にしない
- open-ended意味を有限候補へ閉じ込めない
- independentな観測経路を組み合わせ、agreement / disagreementをtypedに扱う
- disagreement / ambiguityはfail-closed
- 実LLM false accept / false rejectを早期に計測し、Merge Gateへ使う

これは「semantic verificationをLLMへ丸投げする」設計ではない。
LLMは観測candidateを返し、最終acceptanceはRuntime closed policyが所有する。

---

## 3. Production verification topology

```text
SpeechSemanticPlan + CharacterUtterance
        ↓
0. Deterministic Pair / Provenance Gate
        ↓
        ├──────────────────────────────┐
        │                              │
        ▼                              ▼
A. Blind Utterance Observer      B. Plan Relation Observer
   utterance only                  plan + utterance
   no Plan facets                  no Character self-proof
        │                              │
        └──────────────┬───────────────┘
                       ▼
              C. Runtime Reconciliation
                       │
                       ├─ optional closed-facet counterfactual evidence
                       ▼
             SemanticRelationObservation
                       ↓
              Runtime Closed Acceptance
```

AとBは同じCharacter completion後に**並列開始可能**とする。
A完了後にBを開始する固定serial chainへしない。

---

## 4. Stage 0 — Deterministic Pair / Provenance Gate

LLMを呼ぶ前にRuntimeだけで確認する。

- committed `SpeechSemanticPlan`
- committed `CharacterUtterance`
- exact plan / utterance / decision / intent / event identity
- source / goal / attention revision
- current eligibility
- superseded / cancelled
- strict DTO / enum / bounded size

`CharacterUtterance.realization_refs`は構造hintとして保持できるが、A/Bのsemantic proofへ使用しない。

このGateで失敗したpairをsemantic LLMへ送らない。

---

## 5. Observer A — Blind Utterance Observer

### 5.1 目的

Planを見せずにactual utterance内の**material semantic units**を観測し、Plan anchoringでextra claimが消えることを防ぐ。

Aは元のSpeechSemanticPlanを再構築しない。
polarity/certainty/degree等をPlan schemaへround-tripすることも要求しない。

### 5.2 入力

- actual `CharacterUtterance.segments[].text`
- segment identity
- request / trace identity

渡さないもの:

- SpeechSemanticPlan
- expected proposition ID
- expected polarity / certainty / degree
- Character `realization_refs`
- Character candidate自己申告budget
- raw user text / internal state / execution payload

### 5.3 出力

```text
BlindUtteranceObservationCandidate
- request_id
- utterance_id
- units[]

BlindSemanticUnit
- unit_id
- kind: MATERIAL_CLAIM | DIRECTED_QUESTION | NEW_DIRECTION | NON_PROPOSITIONAL_STYLE | AMBIGUOUS
- evidence_refs[]
```

Aの目的は「元のpredicate/valueを完全抽出すること」ではない。
まず**発話中に意味を持つ独立unitがどこに存在するか**をPlan非依存で固定する。

必要な場合のみbounded diagnostic semantic glossをログ/研究用に持てるが、Runtime acceptance Authorityにしない。

### 5.4 Evidence

`segment_id + exact quote + occurrence_index`でgroundする。
Runtimeは位置だけを検証し、quote内単語から意味を再判定しない。

---

## 6. Observer B — Plan Relation Observer

### 6.1 目的

Plan propositionごとにactual utteranceとのrelationを観測する。

Bは「PASSか」を答えない。
各propositionについてclosed relationを返す。

### 6.2 入力

- typed `SpeechSemanticPlan`
- actual `CharacterUtterance.segments[].text`
- pair identity
- relation enum definition

渡さない/信用しないもの:

- Character `realization_refs`をsemantic proofとして利用
- Character budget自己申告をactual speech proofとして利用
- Provider自身の`accepted/pass/score`
- fixed natural-language answer examplesを正解辞書として利用

### 6.3 出力

```text
PlanRelationObservationCandidate
- proposition_relations[]
- unsupported_or_ambiguous_spans[]
- actual_budget_observation
- self_disclosure_relation
```

proposition relation例:

- ENTAILED
- MISSING
- CONTRADICTED
- AMBIGUOUS

closed facet relation:

- polarity: PRESERVED / REVERSED / UNKNOWN_COMMITTED / AMBIGUOUS
- certainty: PRESERVED / STRENGTHENED / WEAKENED / AMBIGUOUS
- degree: PRESERVED / STRENGTHENED / WEAKENED / OMITTED / ADDED / AMBIGUOUS
- execution: PRESERVED / STRENGTHENED / WEAKENED / CONTRADICTED / AMBIGUOUS

これはrelative relationであり、speechからPlan DTO全体を再構築しない。

---

## 7. A/B Runtime Reconciliation

RuntimeはA/Bのcandidateをstrict parse / identity / evidence grounding後にimmutable observer factsへcommitする。

最終`SemanticRelationObservation`はA/B双方を参照する。

### 7.1 Required proposition

- BがENTAILEDである
- B evidenceがactual utteranceへgroundする
- relation facetにreject値がない

### 7.2 Forbidden proposition

- BがENTAILED / AMBIGUOUSならreject

### 7.3 Blind material unit coverage

Aが`MATERIAL_CLAIM`としたunitは、BのPlan relation evidenceまたはBが明示したunsupported/ambiguous observationによってaccountされなければならない。

Aのmaterial unitが**どのB observationにも説明されない場合**:

- `UNACCOUNTED_MATERIAL_CLAIM`
- fail-closed REJECT

これによりPlan-aware Bだけでは見落としやすいPlan外追加をAで露出させる。

### 7.4 Observer disagreement

次を自動acceptしない。

- Aがmaterial claimを検出したがBがstyle-only相当として無視
- Bが強いsemantic evidenceを示すがAがAMBIGUOUS
- evidence groundingがA/Bで整合しない
- BがPlan propositionへ過剰に広いspanを割り当て、Aの複数material unitを一括して隠す

初期policyでは`OBSERVER_DISAGREEMENT`としてfail-closed rejectする。
実LLMデータを理由に、Lab側だけでこのpolicyを緩めない。

---

## 8. Closed-facet Counterfactual Probe — supplemental only

contrastive probeはAcceptance completenessの根拠にしない。

生成してよいのはPlan自体が持つclosed facetの**関係変化**だけ。

例:

- polarity preserved vs reversed
- certainty preserved vs strengthened/weakened
- degree preserved vs strengthened/weakened/omitted
- execution preserved vs completed-strengthening/contradiction

禁止:

- semantic content dictionary
- synonym/antonym list
- predicate/value replacement library
- 「猫→犬」等のcontent-specific fixed candidate
- natural-language phrase candidate generationをRuntime正本にすること

probeはrequest-local / opaque ID / randomized orderとし、正解位置をProviderへ明示しない方式を検証する。

probe resultとB relationが矛盾した場合はPASSへ投票せず`AMBIGUOUS / DISAGREEMENT`として扱う。

---

## 9. Why this differs from V1 failures

### V1 blind round-tripとの違い

AはPlan DTOを再構築しない。
Aの責務はutterance内material unitの独立inventoryとevidence groundingに限定する。

### V1 Plan anchoringとの違い

Bだけを完全性根拠にしない。
Planを知らないAが先入観なしにmaterial unitを観測し、Bが無視したextra contentをRuntime reconciliationで露出させる。

### V1 finite lexical guardとの違い

Runtimeは自然語の単語から意味relationを推定しない。
exact quote matchingはevidence位置確認だけ。

### LLM自己採点との違い

A/B/contrastiveのどれにもfinal PASS Authorityを与えない。
Runtimeがclosed policyからACCEPT/REJECTを導出する。

---

## 10. Remaining uncertainty

この方式も数学的なsemantic proofではない。
A/Bが同じProvider/model familyを使う場合、correlated errorは残り得る。

そのため次をDesign Gateの一部とする。

- model / reasoning policy差の実測
- A/Bを同modelにするか異model classへ分けるかの比較
- same case repeated runs
- unseen paraphrase
- adversarial anchoring case
- unsupported extra claim
- false accept / false reject matrix

Provider/modelを変えるだけで設計欠陥を隠さない。
上位modelだけPASSし軽量baselineが崩れる場合は、contract負荷またはprompt設計を再評価する。

---

## 11. #427 Render Live Validation

#427はこのproduction contractをそのまま呼ぶ。
Lab独自semantic authorityは持たない。

### Production view

- Plan
- Utterance
- A blind inventory
- B plan relations
- optional probe result
- Runtime reconciliation
- final SemanticRelationObservation
- SemanticAcceptance / rejection categories
- latency / token usage / provider failure

### Shadow diagnostics

比較研究目的で:

- A-only
- B-only
- counterfactual-only

を表示してよいが、production acceptanceへ混ぜない。

### V1 failure matrix

最低限:

- unseen paraphrase
- required missing
- forbidden realized
- unknown→yes/no
- certainty strengthen/weaken
- degree strengthen/weaken/omit
- execution completion fabrication
- unsupported extra fact / experience / capability
- optional omission / partial realization
- Plan anchoring trap
- blind extraction trap
- multiple material claims in one sentence
- incorrect Character realization_refs

同じsemantic caseへ複数の自然言語variationを持たせる。
fixture wordingをproduction matcherへ追加してPASSさせることは禁止。

---

## 12. Gate policy

### Design Gate A — PASS_FOR_IMPLEMENTATION_TO_LIVE_VALIDATION

次が確定した時点でproduction branch実装を許可する。

- A/B責務分離
- Runtime reconciliation
- finite lexical authority禁止
- Provider final PASS禁止
- strict evidence grounding
- stale/supersede/cancel gate
- #427 Live Validation計画

これは**Merge PASSではない**。

### Implementation Gate

- production #363 module Unit/Adjacent PASS
- static lexical semantic matcher audit PASS
- fake A/B Provider cases PASS
- current-head deterministic CI PASS

### Live Validation Gate

Render #427でV1 failure matrixを実LLM実行する。

初回baselineでは結果を隠すための都合のよいthresholdを置かない。
false accept / false reject / ambiguity / provider/schema failureをcase単位で記録する。

### Merge Gate

以下を満たすまで#363 product PRはDraft/未mergeを維持する。

- V1既知failure classの重大false acceptが解消
- unseen paraphraseで系統的false rejectが残っていない
- anchoring trap / blind trapの両方を評価済み
- unsupported extra claimの見逃しがacceptance基盤として残っていない
- A/B disagreement policyが実測に基づき確定
- model / reasoning policyが記録済み
- #330 final canonicalと再照合済み

数値acceptance thresholdが必要な場合はbaseline実測後に#363 canonicalへ明示し、Lab側だけで変更しない。

---

## 13. Early implementation dependency

#330 PR #423はVerification中でtrunk未統合。

早期#363 module verificationでは、production `SpeechSemanticPlan`と**fixture/manual CharacterUtterance**を使って#363単体を先行検証できる。

実Character LLM→#363 end-to-endは#330 final canonical再照合後に追加する。

#357 OpenAI Responses Adapterはtrunkへ統合済みなので、#427はproduction `LLMRolePort`から実OpenAIへ接続する。

#363 implementationを#330 current reviewed headへstackする場合は、#330をbase dependencyとして明示し、#330変更時に再照合する。#363を別の重複lineageで作らない。

---

## 14. Design decision

V2 Semantic Verificationは次を採用する。

> **closed relation algebra × open semantic content × independent parallel observations × deterministic fail-closed reconciliation × early real-LLM validation**

contrastive候補集合そのものを意味完全性の根拠にはしない。

自由自然言語を維持する以上残るsemantic uncertaintyは、隠すのではなく#427で継続的に観測し、Merge Gateへ反映する。
