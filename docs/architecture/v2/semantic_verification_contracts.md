# V2 Semantic Verification Contracts

Owner Issue: #363
Parent: #325
Upstream: #323 / #362 / #330
Downstream: #331 / #348 / #334 / #352 / #360
Live Validation: #427
Related:
- `brain_architecture.md`
- `cognitive_llm_architecture.md`
- `speech_semantics_contracts.md`
- `character_language_contracts.md`
- `speech_pipeline_architecture.md`
- `semantic_verification_observer_strategy.md`

Status: Canonical Supplement / Detailed Design Gate

## 1. 目的

#363は、#362 `SpeechSemanticPlan`と#330 `CharacterUtterance`の意味保持関係を独立観測し、Runtimeのclosed policyからexact pairの`SemanticAcceptance`を導出する。

```text
SpeechSemanticPlan + CharacterUtterance
→ deterministic pair gate
→ Plan-blind BlindUtteranceObservation
→ Plan-aware PlanRelationObservation
→ SemanticRelationObservation
→ Runtime closed policy
→ SemanticAcceptance
```

VerifierはWhat-to-say、Character Style、Goal、Runtime Fact、Presentationを決めない。
Providerの`PASS / accepted / score`は最終Authorityではない。

## 2. Authority

- #362: What-to-say Authority
- #330: How-to-say result / CharacterUtterance Authority
- #329: Actual Execution Fact Authority
- #363: semantic observation + exact pair acceptance
- #348: Presentation eligibility / lifecycle Authority

#363はread-only inputからObserver factを作るだけで、Speech Intent、Plan、Runtime Fact、Goal、Internal Stateをmutationしない。

## 3. V1からの禁止事項

- finite natural-language word/phrase/regex/substring semantic matcher
- synonym/antonym dictionaryで意味完全性を証明
- speechから元Plan DTOを完全再構築してexact equality
- Character `realization_refs`をsemantic proofにする
- Character candidate budget自己申告をactual speech proofにする
- Provider free-form reason / confidenceでclosed rejectionをoverride
- Verifierが修正文・固定回答・replacement utteranceを生成
- stale / superseded resultを新しいpairへ流用

## 4. Pair / Snapshot

```text
SemanticVerificationContextSnapshot
- verification_id
- blind_request_id
- relation_request_id
- semantic_plan: SpeechSemanticPlan
- utterance: CharacterUtterance
- llm_priority
- interruptibility
- captured_at
- trace_id
```

構築時にPlan/Utteranceの:

- plan ID
- decision ID
- intent ID
- source event IDs
- `RevisionVector`

を一致させる。

Acceptanceはexact Plan / Utterance pairへbindし、同じPlanから生成した別variantへ流用しない。

## 5. Role A contract

Role ID:

```text
semantic_verification_blind_inventory
```

Role AへPlan、expected facet、Character `realization_refs`を渡さない。

transport/provenance identityは例外で、Providerが推測してはならない。Role inputへtrusted `request_id` / `utterance_id`を明示し、candidateの同名identity fieldは入力値を**exact echo**する。`request_id`は意味情報ではなく、candidateをexact requestへbindするためだけに使い、semantic observationへ影響させない。

```text
BlindSemanticUnit
- unit_id
- kind
- interaction_acts[]
- evidence_refs[]
```

### kind

- `MATERIAL_SEMANTIC_CONTENT`
- `NON_MATERIAL_STYLE`
- `AMBIGUOUS`

### interaction_acts

- `DIRECTED_QUESTION`
- `NEW_DIRECTION`

意味内容とinteraction actは直交する。

`MATERIAL_SEMANTIC_CONTENT`は、命題だけでなく、挨拶、謝意、依頼、約束等の「変えると伝達意味が変わる内容」も含む。

Aはmaterial contentを可能な限りatomic unitへ分ける。1 unitに複数の独立意味が混在し分離不能なら`AMBIGUOUS`。

Role A candidateはstrict schema / identity / evidence grounding後にだけimmutable `BlindUtteranceObservation`へcommitする。

## 6. Evidence contract

```text
UtteranceEvidenceRef
- segment_id
- quote
- occurrence_index
```

ProviderにUnicode offsetを数えさせない。
Runtimeはactual segment内のexact quote occurrenceから位置をgroundする。

このsubstring確認は**evidence locationの検証だけ**であり、Runtimeがquoteの語彙から意味を推定してはならない。

## 7. Role B contract

Role ID:

```text
semantic_verification_plan_relation
```

入力:

- committed `SpeechSemanticPlan`
- actual `CharacterUtterance`
- immutable `BlindUtteranceObservation`
- exact pair identity
- trusted `request_id`

Role B candidateの`request_id / semantic_plan_id / utterance_id / blind_observation_id`は、対応するtrusted input identityを**exact echo**する。Providerが新しいidentityを生成したcandidateはcommitしない。identity echoはsemantic relationの判定材料ではない。

### Proposition relation

Plan propositionごとにexactly one:

- `ENTAILED`
- `MISSING`
- `CONTRADICTED`
- `AMBIGUOUS`

を返す。

relative facet:

- polarity: preserved / reversed / unknown committed / known lost / ambiguous
- certainty: preserved / strengthened / weakened / lost / ambiguous
- degree: preserved / strengthened / weakened / omitted / added / ambiguous
- execution: preserved / strengthened / weakened / contradicted / ambiguous

ENTAILED propositionはactual evidenceとsupporting blind unit IDを持つ。

### Blind unit accounting

blind unitごとにexactly one:

- `SUPPORTED_BY_PLAN`
- `UNSUPPORTED_EXTRA`
- `PERMITTED_NON_MATERIAL_STYLE`
- `AMBIGUOUS`

`SUPPORTED_BY_PLAN`だけがproposition IDsを持てる。

## 8. Bidirectional consistency

A/B対応は双方向にclosed検証する。

1. Accounting `SUPPORTED_BY_PLAN(P)`
   - P relation = ENTAILED
   - Pの`supporting_blind_unit_ids`に同unitが存在
2. Proposition Pがunit Uをsupportに利用
   - U accounting = SUPPORTED_BY_PLAN
   - Uの`proposition_ids`にPが存在

片方向だけの自己申告をcommitしない。

Aの`MATERIAL_SEMANTIC_CONTENT`をBが`PERMITTED_NON_MATERIAL_STYLE`へ降格できない。

1 blind unitにPlan-supported + Plan-extra contentが混在する場合、`SUPPORTED_BY_PLAN`だけで覆うことは禁止し、`UNSUPPORTED_EXTRA`または`AMBIGUOUS`へ送る。

## 9. Budget / self disclosure

Role Aの`interaction_acts`からdirected question / new directionを数える。
Role Bもactual utteranceから独立にcountを返す。

A/B count不一致は`OBSERVER_DISAGREEMENT`。
Plan budget超過はreject。

Self-disclosureはclosed relation:

- WITHIN_POLICY
- EXCEEDED
- NOT_APPLICABLE
- AMBIGUOUS

で扱う。

## 10. CandidateとObserver fact

Provider outputs:

- `BlindUtteranceObservationCandidate`
- `PlanRelationObservationCandidate`

は未確定candidateである。

candidate schemaに次を持たせない。

- accepted / pass / final_decision
- corrected_text / replacement_utterance
- Runtime Fact / Goal mutation
- TTS / Body command

strict gate成功後にだけ:

- `BlindUtteranceObservation`
- `PlanRelationObservation`

をimmutable Observer factとしてcommitする。

## 11. SemanticRelationObservation

```text
SemanticRelationObservation
- observation_id
- verification_id
- blind_observation_id
- relation_observation_id
- semantic_plan_id
- utterance_id
- committed_at
```

これは**観測正本の結合点**であり、accept/reject policyを保持しない。

特に`rejection_categories`を`SemanticRelationObservation`へ持ち込まない。

## 12. SemanticAcceptance

```text
SemanticAcceptance
- acceptance_id
- observation_id
- semantic_plan_id
- utterance_id
- state: ACCEPTED | REJECTED
- rejection_categories[]
- committed_at
```

`state`とcategoriesはRuntime closed policyから導出する。

主なrejection category:

- REQUIRED_PROPOSITION_MISSING
- FORBIDDEN_PROPOSITION_REALIZED
- PROPOSITION_CONTRADICTED
- POLARITY_CHANGED
- CERTAINTY_CHANGED
- DEGREE_CHANGED
- EXECUTION_TRUTH_CHANGED
- UNSUPPORTED_EXTRA_CLAIM
- UNACCOUNTED_MATERIAL_CLAIM
- QUESTION_BUDGET_EXCEEDED
- NEW_DIRECTION_BUDGET_EXCEEDED
- SELF_DISCLOSURE_EXCEEDED
- AMBIGUOUS_SEMANTIC_OBSERVATION
- OBSERVER_DISAGREEMENT

## 13. Acceptance policy

### REQUIRED

- ENTAILED必須
- evidence / supporting unit必須
- closed facetがsafe relation

### OPTIONAL

- MISSINGは許容
- ENTAILEDした場合はREQUIREDと同じfidelityを要求
- CONTRADICTED / AMBIGUOUSはreject

### FORBIDDEN

- ENTAILED / AMBIGUOUSはreject

### Blind material content

Aの`MATERIAL_SEMANTIC_CONTENT`は、Bで`SUPPORTED_BY_PLAN`されなければacceptしない。

- UNSUPPORTED_EXTRA → reject
- AMBIGUOUS → reject
- style降格 → structural reject

### Facets

ENTAILED propositionについて:

- polarity preserved / N/A以外 → reject
- certainty preserved / N/A以外 → reject
- degree preserved / N/A以外 → reject
- execution preserved / N/A以外 → reject

## 14. Freshness

Provider起動前、A await後、B await後に`SemanticVerificationEligibilityView`をlive ownerから再取得する。

```text
SemanticVerificationEligibilityView
- semantic_plan_id
- utterance_id
- revisions
- active
- superseded
- cancelled
```

A後staleならBを呼ばない。
B後stale/superseded/cancelledならObservation/Acceptanceをcommitしない。
開始時のcurrent値をpost-await Authorityへ再利用しない。

## 15. Concurrency

A→Bは初期版ではquality優先のdata dependency。

ただしA/B await中にAuthority lockを保持しない。

継続可能:

- current playback
- Body realtime
- unrelated input / Activity
- #331 Speech Performance
- policy許可されたspeculative TTS preparation

Verifier ACCEPTED前にexternal Presentation commitしない。
REJECTED時にspeculative audioを外部提示しない。

## 16. Failure

- strict schema invalid → no acceptance
- Provider timeout/unavailable/failure → no acceptance
- stale/superseded/cancelled → no acceptance
- ambiguous → fail-closed
- fixed sentence / lexical matcher / Character自己申告へfallbackしない

#363は修正文を生成しない。
retry/regeneration/deferは#348が所有する。

## 17. Counterfactual probe

closed-facet contrastive probeは将来の**補助**であり、初期production completenessの根拠ではない。

固定可能:

- relation algebra
- Planのclosed facet

固定禁止:

- semantic content候補集
- synonym/antonym dictionary
- predicate/value replacement
- content-specific対立パターン
- natural-language phrase library

probeを追加する場合も、通常Observer relationとの矛盾はPASSへ多数決せずambiguity/disagreementとする。

## 18. Static regression policy

`app/domain/semantic_verification`にはopen-ended semantic decision用の:

- `re`
- keyword list
- marker list
- phrase list
- synonym list
- antonym list

を導入しない。
Architecture test/static AST auditで再侵入を検出する。

Protocol token、enum、schema field名等のclosed technical identifierはこの禁止対象ではない。

## 19. Verification

### Unit / Adjacent

最低限:

- blind requestへPlan/realization refs非漏洩
- Role A/B request identityをProvider inputへ明示し、candidateがexact echoできる
- Providerがidentityを推測・再生成しなくてもAuthority commit可能
- preserved required + missing forbidden ACCEPT
- material content + directed question同時成立
- material content→style降格reject
- A/B bidirectional accounting mismatch reject
- evidence quote grounding failure reject
- unsupported extra material content reject
- stale after A → B非実行
- strict schema invalid
- duplicate/unknown IDs
- finite lexical semantic authority static audit

### Real LLM — #427

V1 failure matrixをRenderで実行する。

- unseen paraphrase
- required / optional / forbidden
- polarity
- unknown
- certainty
- degree
- execution truth
- unsupported extra
- Plan anchoring trap
- blind extraction trap
- compound semantic contents
- material content + question
- wrong Character realization refs

## 20. Gate

### Design Gate A

`PASS_FOR_IMPLEMENTATION_TO_LIVE_VALIDATION`

### Implementation Gate

- Unit / Adjacent
- Ruff
- Mypy strict
- full pytest
- compileall
- diff check
- static lexical audit
- exact-head CI
- current-head review

### Live Validation Gate

#427 Renderでproduction #363 + production #357 Adapterを実LLM実行する。

### Merge Gate

次を満たすまでDraft/未merge:

- V1重大false accept解消
- unseen paraphrase系統false rejectなし
- Plan anchoring / blind extraction両trap評価
- unsupported extra見逃しが基盤として残らない
- A/B disagreement policy妥当
- model/reasoning policy記録
- latency/non-blocking確認
- #330 final canonical再照合

## 21. 非目標

- 正解日本語文の固定
- Characterらしさ採点
- finite phrase guard
- semantic proofの数学的完全性を装うこと
- TTS/Body/Presentationのcommit

詳細なObserver strategy / Render matrixは`semantic_verification_observer_strategy.md`を正本とする。
