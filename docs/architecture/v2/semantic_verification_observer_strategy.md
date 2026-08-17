# V2 Semantic Verification Observer / Live Validation Strategy

Owner Issue: #363
Validation Work: #427
Parent: #325
Upstream: #362 / #330
Provider: #357
Related: #348 / #352
Status: Canonical Supplement / Implementation-to-Live-Validation Gate

## 1. 目的

V1 #288 / #293 / #303で確認したSemantic Verificationの失敗をV2へ持ち込まないため、open-ended Character発話の意味保持を**本番Module + 実LLM**で早期検証する。

V1では両方向の失敗を経験した。

1. blind extraction / speech→元semantic enum再構成
   - certainty / unknown / degree / concept等でfalse reject
   - schema負荷が高い
2. Plan-aware verification
   - expected facetへのanchoringでfalse acceptし得る

さらにfinite word / phrase / regex / substring / synonym / antonym listをsemantic authorityへ使う方式は、unseen paraphrase、辞書肥大、test wording最適化を起こした。

V2では、どれか1方式を万能なsemantic proofとみなさない。

## 2. 基本原則

自由自然言語に完全な決定論的semantic proofはない。
そのため次を守る。

- open-ended意味を有限候補集へ閉じ込めない
- Runtimeは自然語keywordから意味を推定しない
- 1つのVerifier LLMの自己判定をPASS根拠にしない
- Planを見ない観測でactual utteranceのmaterial semantic contentを先に固定する
- Plan-aware観測は先行blind observationを消去・改名・再分類できない
- ambiguity / observer disagreementはfail-closed
- Providerの`PASS / accepted / score`を最終Authorityにしない
- Characterの`realization_refs` / budget自己申告をsemantic proofにしない
- 最終accept/rejectはRuntime closed policyが所有する
- 実LLM false accept / false rejectをMerge Gateへ含める

## 3. Production topology

初期productionは品質優先の2-stage observerとする。

```text
SpeechSemanticPlan + CharacterUtterance
        ↓
0. Deterministic Pair / Provenance Gate
        ↓
A. Plan-blind Utterance Inventory Observer
        ↓
   immutable BlindUtteranceObservation
        ↓
B. Plan Relation Observer
   Plan + Utterance + frozen blind units
        ↓
   immutable PlanRelationObservation
        ↓
C. Runtime deterministic reconciliation
        ↓
   SemanticRelationObservation
        ↓
D. Runtime closed acceptance policy
        ↓
   SemanticAcceptance
```

A→Bはsemantic safety上のdata dependencyであるため、初期版では無理に並列化しない。
ただしA/B await中もcurrent playback、Body realtime、unrelated input/Activity、#331 Speech Performance、policy許可されたspeculative TTS preparationは停止させない。

## 4. Role A — Plan-blind Inventory

Role ID:

```text
semantic_verification_blind_inventory
```

### 入力

- actual `CharacterUtterance.segments[].text`
- segment identity
- request / trace identity

渡さないもの:

- `SpeechSemanticPlan`
- proposition ID
- expected polarity / certainty / degree / execution
- Character `realization_refs`
- Character budget自己申告
- raw user text / internal state / execution payload

### 出力

Role AはPlan DTOを再構築しない。
actual utteranceを最小のsemantic unitへ分ける。

```text
BlindSemanticUnit
- unit_id
- kind
- interaction_acts[]
- evidence_refs[]
```

`kind`:

- `MATERIAL_SEMANTIC_CONTENT`
- `NON_MATERIAL_STYLE`
- `AMBIGUOUS`

`interaction_acts`:

- `DIRECTED_QUESTION`
- `NEW_DIRECTION`

意味内容とinteraction actは**直交**する。

例:

```text
「今日は雨だよね？」
→ kind = MATERIAL_SEMANTIC_CONTENT
→ interaction_acts = [DIRECTED_QUESTION]
```

命題だけでなく、挨拶、謝意、依頼、約束等も、変えると伝達意味が変わるなら`MATERIAL_SEMANTIC_CONTENT`として扱う。
語尾・言い淀み等で独立した伝達意味を持たない表面だけを`NON_MATERIAL_STYLE`とする。

独立した意味を1 unitへまとめるとPlan外claimを隠し得るため、可能な限りatomicに分割する。分離不能なら`AMBIGUOUS`としfail-closed側へ送る。

## 5. Evidence grounding

LLMへ文字offsetを数えさせない。

```text
UtteranceEvidenceRef
- segment_id
- quote
- occurrence_index
```

Runtimeはactual segment内のexact quote occurrenceを位置groundingするだけである。
quote内の単語からpolarity / certainty / degree / claim kind等を再推定しない。

## 6. Role B — Plan Relation / Accounting

Role ID:

```text
semantic_verification_plan_relation
```

### 入力

- typed `SpeechSemanticPlan`
- actual `CharacterUtterance`
- immutable `BlindUtteranceObservation`
- exact pair identity
- closed relation enum definition

### Plan proposition relation

各Plan propositionについてexactly one:

- `ENTAILED`
- `MISSING`
- `CONTRADICTED`
- `AMBIGUOUS`

を返す。

closed semantic facetはPlanに対する**relative relation**として観測する。

- polarity: preserved / reversed / unknown committed / ambiguous
- certainty: preserved / strengthened / weakened / ambiguous
- degree: preserved / strengthened / weakened / omitted / added / ambiguous
- execution: preserved / strengthened / weakened / contradicted / ambiguous

speechからPlan DTO全体をround-trip再構築しない。

### Blind unit accounting

Aの各unitについてexactly one accountingを返す。

- `SUPPORTED_BY_PLAN`
- `UNSUPPORTED_EXTRA`
- `PERMITTED_NON_MATERIAL_STYLE`
- `AMBIGUOUS`

`SUPPORTED_BY_PLAN`だけがproposition IDを持てる。

A/Bは双方向に一致しなければならない。

- Accountingが`SUPPORTED_BY_PLAN(P)`なら、P側も`ENTAILED`で同じblind unitをsupportとして参照する
- Proposition Pがblind unit Uをsupportに使うなら、U側accountingも`SUPPORTED_BY_PLAN`でPを参照する

片方向だけの自己申告ではcommitしない。

Aの`MATERIAL_SEMANTIC_CONTENT`をBがstyleへ降格することは禁止する。
1 blind unitにPlan-supported意味とPlan外意味が混在している場合、Bは`SUPPORTED_BY_PLAN`だけで覆わず`UNSUPPORTED_EXTRA`または`AMBIGUOUS`とする。

## 7. Speech act / budget

Aの`interaction_acts`と、Bがactual utteranceから独立観測したdirected question / new direction countをRuntimeで照合する。

A/B countが不一致なら`OBSERVER_DISAGREEMENT`。
Planのquestion/new-direction budgetを超過すればrejectする。

Character candidateのbudget自己申告はsemantic acceptance Authorityにしない。

## 8. Runtime structural gate

Provider candidateをそのままRuntime正本にしない。

### A commit前

- request / utterance identity
- strict schema / closed enum
- unit ID uniqueness / bounds
- exact evidence grounding

### B commit前

- exact Plan / Utterance / BlindObservation identity
- Plan proposition全件exactly one observation
- blind unit全件exactly one accounting
- unknown/duplicate IDなし
- proposition evidenceがsupporting blind unit evidenceへground
- A↔B bidirectional support/accounting consistency
- material content→style降格禁止

成功後だけimmutable A/B Observationを構築する。

## 9. SemanticRelationObservationとAcceptanceの分離

`SemanticRelationObservation`は**Observer fact**であり、accept/reject policyを内包しない。

保持するのは:

- exact pair identity
- BlindUtteranceObservation ID
- PlanRelationObservation ID
- commit timestamp

とする。

`rejection_categories`は`SemanticAcceptance`だけが所有する。

これにより、観測結果と現在のclosed acceptance policyを分離する。
Provider candidateにもfinal accept/pass fieldを持たせない。

## 10. Closed acceptance policy

Runtimeはimmutable A/B observations + authoritative Planからaccept/rejectを導出する。

主なreject:

- required proposition missing
- forbidden proposition realized / ambiguous
- proposition contradicted
- polarity changed
- certainty strengthened / weakened / lost
- degree strengthened / weakened / omitted / added
- execution truth strengthened / weakened / contradicted
- unsupported material semantic content
- unaccounted material semantic content
- question / new-direction budget exceeded
- self-disclosure exceeded / ambiguous
- A/B ambiguity / disagreement

`naturalだから`、`Characterらしいから`、`Provider confidenceが高いから`でoverrideしない。

## 11. Counterfactual / contrastive probe

contrastive verificationは**補助機構のみ**で、初期production completenessの根拠にしない。

固定してよいもの:

- relation algebra
- Planが元から持つclosed facet

禁止:

- semantic content候補集
- synonym / antonym dictionary
- predicate/value replacement library
- content-specific対立パターン
- natural-language phrase candidate library

将来導入する場合はrequest-localにclosed facet counterfactualだけを生成し、通常relationと矛盾したら投票多数決でPASSせずambiguity/disagreementへ送る。

## 12. V1との差

### blind round-tripではない

Role Aは元semantic enumを再構築しない。
Planを見ず、material content inventoryとevidenceだけを固定する。

### Plan anchoringだけに依存しない

Role BがPlanを見ても、Role Aが先に固定したmaterial contentを消せない。
全blind unitへaccounting obligationを課す。

### finite lexical matcherを使わない

Runtimeは自然文の表面語彙から意味を判定しない。
static testでsemantic moduleへの`re`やkeyword/marker/phrase/synonym/antonym型semantic scaffolding再侵入を監査する。

### LLM自己採点を使わない

A/Bのどちらにもfinal PASS Authorityを渡さない。

## 13. Freshness / stale / cancellation

Provider起動前、A完了後、B完了後にlive pair stateを再取得する。

確認:

- semantic plan ID
- utterance ID
- source / goal / attention revision
- active
- superseded
- cancelled

A後にstaleならBを呼ばない。
B後にstaleならObservation/Acceptanceをcommitしない。
開始時のcurrent値をpost-await Authorityとして再利用しない。

## 14. Failure policy

- A schema/provider failure → acceptance生成なし
- A ambiguity → fail-closed
- B schema/provider failure → acceptance生成なし
- B ambiguity/disagreement → reject
- Provider unavailable → fixed sentence / regex / Character自己申告へfallbackしない
- #363はreplacement utteranceを生成しない

regeneration/retryは#348 Speech preparation policyがboundedに制御する。

## 15. #427 Render Live Validation

#427はこのproduction contractをそのまま呼ぶ。
Lab独自semantic logicやLab専用Verifier Promptでproductionを置換しない。

表示対象:

- SpeechSemanticPlan
- CharacterUtterance
- Stage 0 pair gate
- Role A blind units / interaction acts / evidence
- Role B proposition relations
- Role B blind-unit accounting
- SemanticRelationObservation
- SemanticAcceptance / rejection categories
- A latency / B latency / total
- token usage
- provider/schema/stale/cancel failure

### V1 failure matrix

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
- multiple material contents in one sentence
- proposition + question simultaneous
- overlapping proposition realization
- incorrect Character realization_refs
- question/new-direction budget

同じsemantic caseに複数の自然言語variationを用意し、fixture wordingをproduction matcherへ追加してPASSさせることは禁止する。

## 16. Model / latency evaluation

A/Bが同じProvider/model familyならcorrelated errorは残り得る。
#427で最低限比較する。

- same model A/B
- A軽量 + B高精度
- A/B別model class
- reasoning effort差
- repeated runs

上位modelだけ通る場合はmodel切替だけで解決扱いせず、contract/prompt負荷を再評価する。

品質確立後にのみbatch/fusion/parallel optimizationを検討する。

## 17. Gate policy

### Design Gate A

`PASS_FOR_IMPLEMENTATION_TO_LIVE_VALIDATION`

本番Moduleを作って実LLM検証へ進む責務境界は確定。

### Implementation Gate

- Unit / Adjacent PASS
- Ruff
- Mypy strict
- full pytest
- compileall
- diff check
- finite lexical semantic authority static audit
- exact-head CI
- current-head code review

### Live Validation Gate

Render #427でV1 failure matrixを実LLM実行する。
初回baselineで都合のよいthresholdを後付けしない。
false accept / false reject / ambiguity / provider failureをcase単位で記録する。

### Merge Gate

次を満たすまで#363 product PRはDraft/未merge。

- V1既知failure classの重大false acceptが解消
- unseen paraphraseで系統的false rejectが残らない
- anchoring trap / blind trap両方評価済み
- unsupported extra claim見逃しが基盤として残らない
- A/B disagreement policyが実測で妥当
- model/reasoning policy記録済み
- latency/non-blocking invariant確認
- #330 final canonical再照合

## 18. Design decision

V2初期productionは次を採用する。

> **Plan-blind atomic semantic inventory + orthogonal interaction acts → Plan-aware bidirectional relation/accounting → pure Observer fact → deterministic fail-closed Acceptance → early real-LLM Render validation**

固定候補集合を意味完全性の根拠にしない。
自由自然言語に残るsemantic uncertaintyは隠さず、#427の実LLM観測をMerge Gateへ組み込む。
