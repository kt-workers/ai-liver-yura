# V2 Semantic Verification Contracts

Owner Issue: #363
Parent: #325
Upstream: #323 / #362 / #330
Downstream: #331 / #348 / #334 / #352 / #360
Related canonical:
- `docs/architecture/v2/brain_architecture.md`
- `docs/architecture/v2/cognitive_llm_architecture.md`
- `docs/architecture/v2/concurrency_architecture.md`
- `docs/architecture/v2/speech_semantics_contracts.md`
- `docs/architecture/v2/character_language_contracts.md`
- `docs/architecture/v2/speech_pipeline_architecture.md`
Status: Canonical Supplement / Detailed Design Gate

## 1. 目的

#363 Semantic Verificationは、#362が確定した`SpeechSemanticPlan`と、#330が生成・構造検証した`CharacterUtterance`の**意味関係を独立に観測**し、closed typed relationへ変換する。

```text
SpeechSemanticPlan            # What-to-say Authority
+ CharacterUtterance          # How-to-say result, semantic proofではない
        ↓
Independent Semantic Verification
        ↓
SemanticRelationObservation   # immutable Observer fact about the pair
        ↓
deterministic closed policy
        ↓
SemanticAcceptance            # exact Plan / Utterance pairにだけ有効
```

VerifierはSpeech Intent、発言内容、Character Style、Runtime Factを決めない。
LLMが`PASS`と答えたことを最終Authorityにしない。

目的は「正解の日本語文」を固定することではない。同じ`SpeechSemanticPlan`から多様なCharacter表現を許容しつつ、意味の欠落・反転・強弱変更・unknownの勝手な確定・未根拠の追加claimを検出することである。

---

## 2. Authority境界

### 2.1 上流Authority

- #362 `SpeechSemanticPlan`: What-to-sayの唯一のAuthority。
- #330 `CharacterUtterance`: Characterらしい実現結果。semantic acceptance Authorityではない。
- #329: Actual Execution FactのAuthority。
- #348: Presentation lifecycleと現在のcandidate eligibilityのAuthority。

#363はこれらをread-onlyで参照する。

### 2.2 #363が所有するもの

- Plan propositionとactual utteranceの相対的意味関係の観測
- actual utterance textへgroundされたevidence
- unsupported extra semantic claimの観測
- actual question / new-direction使用量のsemantic observation
- immutable `SemanticRelationObservation`
- closed policyによるexact Plan / Utterance pairのaccept/reject
- rejection categoryのtyped診断

### 2.3 禁止

- Speech Intent / proposition / truth constraintの変更
- Characterへ修正文・正解文・固定言い換えを直接命令
- Character Profileの採点
- Runtime Fact / Goal / Internal State / Attentionのmutation
- raw user textの再解釈
- finite word / phrase / regex / substringによるopen-ended意味判定
- free-form `accepted`, `reason`, `score`を最終accept/reject Authorityとして利用
- Character自身の`realization_refs`を意味保持の証明として採用
- TTS / Body / Presentationのcommit

---

## 3. 「独立Observer」の意味

独立とは、Verifierが期待Planを知らないことではない。VerifierはPlanとUtteranceの**相対関係を比較する**ため、typed Planを入力に利用する。

独立性は次で確保する。

1. Character生成と別logical role / request / result identityを持つ。
2. Character LLMの自己申告、`realization_refs`、budget自己申告をsemantic proofにしない。
3. actual `CharacterUtterance.segments[].text`を必ず観測する。
4. REALIZED relationやextra claimをactual text evidenceへgroundする。
5. Providerは最終`PASS`を決めず、closed relation candidateだけを返す。
6. Runtimeがschema / identity / grounding / policyを決定論的に検証する。

V1で問題になった「speechから元enumを完全再構成してexact equalityする」方式を正規形にしない。
Planの各facetに対し、発話が`preserved / strengthened / weakened / contradicted / missing / ambiguous`等の**相対関係**を持つかを観測する。

---

## 4. SemanticVerificationContextSnapshot

Verifier起動時にimmutable snapshotをfreezeする。

```text
SemanticVerificationContextSnapshot
- request_id
- semantic_plan: SpeechSemanticPlan
- utterance: CharacterUtterance
- verification_requirement
- llm_priority
- interruptibility
- captured_at
- trace_id
```

構築条件:

- Planは#362 Authority経由でcommit済み。
- Utteranceは#330 Authority経由でcommit済み。
- utteranceの`semantic_plan_id / decision_id / intent_id / source_event_ids / RevisionVector`がPlanと一致。
- `realization_refs`はhintとして保持するが観測結果を事前確定しない。
- raw user text、raw Emotion / Desire / Drive、unbounded history、Provider SDK objectを追加しない。
- `llm_priority / interruptibility`はSpeech preparation scheduling境界からread-onlyで受け取り、#363が内容から推測しない。

### 4.1 Pair identity

```text
SemanticVerificationPair
- semantic_plan_id
- utterance_id
- source_decision_id
- source_intent_id
- revisions: RevisionVector
```

Acceptanceは常にexact pairへbindする。
同じPlanからregenerationされた別Utteranceへ結果を流用しない。

---

## 5. Verification requirement / skip policy

Architecture上、将来同等以上の決定論的保証があるpathではVerifier省略を許容できる。ただしv1で「low risk」という曖昧な理由だけのskipは認めない。

```text
SemanticVerificationRequirement
- REQUIRED
- DETERMINISTIC_PROOF
```

### REQUIRED

現在の#330のようなopen-ended LLM Character realizationはすべて`REQUIRED`。

### DETERMINISTIC_PROOF

Verifier callを省略できるのは、将来の別typed realization pathが`DeterministicSemanticProof`を生成できる場合だけ。

最低条件:

- exact Plan / Utterance pairへbind
- proof producerがtrusted typed path
- open-ended LLM outputをproofとして扱わない
- finite phrase辞書をsemantic proofにしない
- proof schema / producer authorityを別Design Gateで定義

**現行#330 v1にはこのpathが存在しないため、全LLM CharacterUtteranceがVerifier必須である。**

---

## 6. Evidence grounding

LLMにUnicode文字offsetを直接数えさせない。evidenceはProviderがactual segmentからexact quoteを返し、Runtimeが決定論的に位置解決する。

```text
UtteranceEvidenceRef
- segment_id
- quote
- occurrence_index
```

Runtime grounding:

1. `segment_id`をactual `CharacterUtterance`へexact resolveする。
2. `quote`はnon-emptyかつbounded長。
3. segment text内で`quote`の**exact substring occurrence**を列挙する。
4. `occurrence_index`は0-based concrete intとして該当occurrenceを一意選択する。
5. Runtimeが内部的にUnicode code-point start/end offsetを導出する。

このexact substring確認は**evidence位置のgroundingだけ**に使う。quote内の単語からpolarity/certainty/degree等をRuntimeが再推定しない。

- unknown segment、存在しないquote、範囲外occurrenceを拒否。
- 1 relation当たりのevidence数、candidate全体のevidence数をboundedにする。
- Providerが返す別のfree-form引用説明をAuthorityにしない。

`CharacterUtteranceSegment.realization_refs`と`UtteranceEvidenceRef`は別物。
realization refが正しくてもactual textが意味を保持しなければacceptしない。

---

## 7. Proposition relation contract

Plan上の各`SpeechProposition`についてexactly oneの観測recordを返す。

```text
PropositionSemanticObservation
- proposition_id
- presence
- polarity_relation
- certainty_relation
- degree_relation
- execution_relation
- evidence_refs[]
```

### 7.1 Presence

```text
PropositionPresence
- REALIZED
- NOT_REALIZED
- AMBIGUOUS
```

### 7.2 Polarity relation

```text
PolarityRelation
- PRESERVED
- REVERSED
- UNKNOWN_COMMITTED_AFFIRM
- UNKNOWN_COMMITTED_NEGATE
- KNOWN_LOST_TO_UNKNOWN
- NOT_APPLICABLE
- AMBIGUOUS
```

Planが`UNKNOWN`なのにCharacterがyes/noへ確定した場合は`UNKNOWN_COMMITTED_*`。

### 7.3 Certainty relation

```text
CertaintyRelation
- PRESERVED
- STRENGTHENED
- WEAKENED
- LOST_TO_UNKNOWN
- NOT_APPLICABLE
- AMBIGUOUS
```

`likely → certain`、`uncertain → certain`等はSTRENGTHENED。
`certain → likely`等はWEAKENED。

### 7.4 Degree relation

```text
DegreeRelation
- PRESERVED
- STRENGTHENED
- WEAKENED
- OMITTED
- ADDED
- NOT_APPLICABLE
- AMBIGUOUS
```

Runtimeは程度語dictionaryからdegreeを推定しない。VerifierがPlanに対するrelative relationとして観測する。

### 7.5 Execution truth relation

```text
ExecutionTruthRelation
- PRESERVED
- STRENGTHENED
- WEAKENED
- CONTRADICTED
- NOT_APPLICABLE
- AMBIGUOUS
```

例:

- Planがrequested / not completedなのに発話がcompletedを意味する → STRENGTHENEDまたはCONTRADICTED
- Planがcompletedを許すのに発話が未実行を意味する → CONTRADICTED

Execution status文字列をspeechからregex抽出しない。

---

## 8. REQUIRED / OPTIONAL / FORBIDDEN

Plan dispositionをVerifier candidateに再定義させない。RuntimeはPlanをAuthorityとしてclosed policyを適用する。

### REQUIRED

- REALIZED必須。
- semantic facet relationが全てaccept可能。
- REALIZEDなら最低1つのvalid evidence refを要求。

### OPTIONAL

- NOT_REALIZEDは許容。
- REALIZEDした場合はREQUIREDと同じsemantic fidelityを要求。

### FORBIDDEN

- NOT_REALIZEDのみ許容。
- REALIZEDまたはAMBIGUOUSはfail-closed reject。
- Character側がFORBIDDEN refを付けていないことだけでは非実現の証明にならない。

---

## 9. Unsupported extra semantic claim

Plan propositionへgroundできない**新しいsemantic claim**を別契約で観測する。

```text
UnsupportedSemanticClaimObservation
- claim_id
- relation: UNSUPPORTED_SEMANTIC_CLAIM | AMBIGUOUS_EXTRA
- evidence_refs[]
```

- 語尾、言い淀み、非命題的なCharacter Styleをextra claim扱いしない。
- 新しい事実、経験、能力、実行完了、自己状態等を意味的に追加した場合だけ対象。
- free-form説明をacceptance Authorityにしない。
- `UNSUPPORTED_SEMANTIC_CLAIM`が1件でもあればreject。
- `AMBIGUOUS_EXTRA`もfail-closed reject。

この観測は新しいRuntime Factを作らない。

---

## 10. Speech act / budget observation

#330の`question_budget_used / new_direction_budget_used`は構造的自己申告でありactual speechのsemantic proofではない。#363でactual utteranceを独立観測する。

```text
SpeechActBudgetObservation
- directed_question_count
- new_direction_count
- evidence_refs[]
```

- finite question-ending regex、疑問詞dictionary、topic bigramで判定しない。
- countはnon-negative concrete int。bool-as-intを拒否。
- RuntimeはPlanのbudgetと決定論的に比較する。
- #330自己申告と不一致でも、#363 actual observationをsemantic acceptance側に使う。

Self-disclosureもclosed relationで観測する。

```text
SelfDisclosureRelation
- WITHIN_POLICY
- EXCEEDED
- AMBIGUOUS
- NOT_APPLICABLE
```

---

## 11. SemanticVerificationCandidate

LLM Provider出力は未確定candidate。

```text
SemanticVerificationCandidate
- candidate_id
- request_id
- semantic_plan_id
- utterance_id
- source_decision_id
- source_intent_id
- source_event_ids[]
- revisions: RevisionVector
- proposition_observations[]
- unsupported_claims[]
- budget_observation
- self_disclosure_relation
- observed_at
```

Candidateに存在してはいけないfield:

- `accepted`
- `pass`
- `final_decision`
- `corrected_text`
- `replacement_utterance`
- `repair_prompt`
- rewritten proposition
- Runtime Fact
- Goal / State mutation
- TTS / Body command

free-form診断を保持する場合もbounded diagnosticに限定し、acceptanceへ使用しない。

---

## 12. Semantic Verification Role

```text
role_id: semantic_verification
input_schema_id: semantic.verification.context.v1
output_schema_id: semantic.verification.candidate.v1
```

Foundation #323の`LLMRoleDescriptor / LLMRoleRequest / LLMRoleResult / LLMRolePort / validate_role_exchange()`を利用する。

### 12.1 LLM input

入力は次に限定する。

1. Planのtyped proposition / disposition / semantic facet
2. actual CharacterUtterance segments
3. exact pair / request provenance
4. closed relation enumの意味

Character Profile、raw Internal State、raw user input、unbounded historyを渡さない。
VerifierはCharacterらしさを採点しない。

### 12.2 Providerへの要求

「PASS/FAILを決めよ」ではなく、**各propositionとactual utteranceのrelationを観測せよ**と要求する。

Plan-aware comparisonは許可するが、Plan値のechoだけでは足りない。REALIZED relationとextra claimにはactual text evidence groundingを要求する。

### 12.3 Provider failure

schema invalid / timeout / cancellation / provider unavailableではObservationもAcceptanceも生成しない。
generic fixed sentenceやCharacter自己申告で成功へfallbackしない。
retryはFoundation Role policyに従いboundedにする。

---

## 13. Candidate structural / provenance gate

`SemanticVerificationAuthority`はProvider await外の短いdeterministic処理だけを行う。

最低限:

1. Foundation role/schema/request/result identity一致。
2. request ID / Plan ID / Utterance ID一致。
3. decision / intent / source Event IDs一致。
4. RevisionVector一致。
5. Plan propositionごとにexactly one observation。
6. unknown/duplicate proposition ID拒否。
7. closed enum以外拒否。
8. REALIZED propositionのevidence refがactual segment textへvalidにground。
9. NOT_REALIZEDで意味のあるevidenceを捏造しない。
10. unsupported claim evidenceもactual textへground。
11. evidence数・claim数・candidate sizeのbounded制約。
12. budget countはconcrete non-negative int。
13. final acceptance / corrected text / mutation fieldをstrict schemaで拒否。

構造検証成功はまだPresentation acceptanceではない。

---

## 14. SemanticRelationObservation

Candidate structural/provenance gateを通過した後、#363 Authorityだけがimmutable Observationを構築する。

```text
SemanticRelationObservation
- observation_id
- pair: SemanticVerificationPair
- source_candidate_id
- proposition_observations[]
- unsupported_claims[]
- budget_observation
- self_disclosure_relation
- grounded_at
- committed_at
```

性質:

- Provider candidateそのものをRuntime正本にしない。
- 全evidence refはRuntime解決済みgroundingを持つ。
- exact Plan / Utterance pair以外へ流用不可。
- Observationは「話してよい」命令ではなく、pairに関するtyped observer result。
- free-form reason / scoreはObservationのacceptance Authorityにならない。

同じcandidate payloadを別pairへ付け替えない。

---

## 15. Closed deterministic acceptance policy

Runtimeはvalidated `SemanticRelationObservation`とPlanからのみaccept/rejectを導出する。

### 15.1 ACCEPTED条件

すべて満たすこと。

- REQUIRED: REALIZED。
- OPTIONAL: NOT_REALIZEDまたは安全にREALIZED。
- FORBIDDEN: NOT_REALIZED。
- REALIZED propositionのpolarity = PRESERVED or NOT_APPLICABLE。
- certainty = PRESERVED or NOT_APPLICABLE。
- degree = PRESERVED or NOT_APPLICABLE。
- execution = PRESERVED or NOT_APPLICABLE。
- unknownをaffirm/negateへcommitしていない。
- unsupported semantic claim = 0。
- ambiguous relation = 0。
- actual question count <= Plan budget。
- actual new-direction count <= Plan budget。
- self-disclosure = WITHIN_POLICY or NOT_APPLICABLE。

### 15.2 REJECTED条件

次のどれか1つでreject。

- required missing
- forbidden realized / ambiguous
- polarity reversed / unknown committed / known lost
- certainty strengthened / weakened / lost / ambiguous
- degree strengthened / weakened / omitted / added / ambiguous
- execution truth strengthened / weakened / contradicted / ambiguous
- unsupported / ambiguous extra semantic claim
- question budget exceeded
- new-direction budget exceeded
- self-disclosure exceeded / ambiguous
- required semantic relation ambiguous

「自然だから」「Characterらしいから」「confidenceが高いから」でoverrideしない。

---

## 16. SemanticAcceptance

```text
SemanticAcceptance
- acceptance_id
- pair: SemanticVerificationPair
- observation_id
- state: ACCEPTED | REJECTED
- rejection_categories[]
- committed_at
```

`state`はProvider outputではなくRuntime closed policyから導出する。
`observation_id`は§14のimmutable `SemanticRelationObservation`へexactly oneでbindする。

Rejection category例:

- REQUIRED_PROPOSITION_MISSING
- FORBIDDEN_PROPOSITION_REALIZED
- POLARITY_CHANGED
- CERTAINTY_CHANGED
- DEGREE_CHANGED
- UNKNOWN_COMMITTED
- EXECUTION_TRUTH_CHANGED
- UNSUPPORTED_EXTRA_CLAIM
- QUESTION_BUDGET_EXCEEDED
- NEW_DIRECTION_BUDGET_EXCEEDED
- SELF_DISCLOSURE_EXCEEDED
- AMBIGUOUS_SEMANTIC_OBSERVATION

---

## 17. Regeneration boundary

REJECTED時:

```text
SemanticAcceptance(REJECTED, categories)
→ Speech preparation / orchestration
→ 必要なら同じSpeechSemanticPlanで#330へnew variant要求
→ new CharacterUtterance
→ new exact pairとして#363再検証
```

#363は修正文、fixed replacement phrase、新propositionを生成しない。
retry / reject / defer / replanningは上位Speech runtime policyが決める。

---

## 18. Freshness / stale / supersede

Semantic relationはimmutable pairへbindするが、active Speech candidateとしてObservation/Acceptanceをcommitする前にlive eligibilityを再確認する。

`SemanticVerificationLiveStatePort`はread-onlyで最低限:

```text
SemanticVerificationEligibilityView
- semantic_plan_id
- utterance_id
- revisions: RevisionVector
- active
- superseded
- cancelled
```

### Preflight

Provider起動前にpairがactiveであることを確認。

### Post-await gate

Provider完了後・Observation/Acceptance commit直前にlive viewを**再取得**し:

- pair identity一致
- source / goal / attention revision一致
- active=true
- superseded=false
- cancelled=false

を要求する。

開始時に取得した`current_*`値をpost-await Authorityとして再利用しない。
stale / superseded resultを新しいUtteranceへ付け替えない。
Provider待機中にglobal lockを保持しない。

Presentation直前の最終eligibilityは#348が再検証するため、#363 acceptanceだけで外部提示権限は成立しない。

---

## 19. Concurrency / idempotency

- Verifier LLM await中にDomain Authority lockを保持しない。
- current Speech playback / Body realtime / unrelated input / Activityをblockしない。
- Character completion後、#331 Speech PerformanceとVerifierを並列開始可能。
- #348 policyが許す場合、speculative TTS prepも並列可能。
- Verifier ACCEPTED前にPresentation commit不可。
- Verifier REJECTED時speculative resultを外部提示しない。

同じexact pairに複数requestが競合した場合、同じObservation/Acceptance identityのdouble commitを拒否する。
再試行は新request identityで監査できるが、古いretry結果でnewer accepted resultを上書きしない。

---

## 20. Observability

最低限:

- verification queued / started / completed
- provider latency / queue wait
- Plan / Utterance pair IDs
- source / goal / attention revisions
- accepted / rejected / stale / cancelled / provider failure
- rejection category counts
- regeneration count
- unsupported-extra / ambiguity率
- false accept / false rejectのVerification fixture結果

通常traceへraw Prompt、Provider raw response、secretを出さない。
必要以上にutterance本文を複製ログへ保存せず、pair / evidence ref中心にする。

---

## 21. Unit / Adjacent Acceptance

### Relation Unit

- REQUIRED exact/paraphrase realization → ACCEPT
- OPTIONAL omitted → ACCEPT
- OPTIONAL realized with preserved facets → ACCEPT
- REQUIRED missing → REJECT
- FORBIDDEN realized → REJECT
- polarity reversal → REJECT
- certainty strengthen / weaken → REJECT
- degree strengthen / weaken / omit / add → REJECT
- UNKNOWNをaffirm / negateへcommit → REJECT
- execution status未完了→完了へ強化 → REJECT
- unsupported new fact / experience / capability claim → REJECT
- semantic ambiguity → fail-closed REJECT

### Evidence / Schema

- valid multi-segment exact quote grounding
- repeated quoteは`occurrence_index`で一意化
- missing quote / unknown segment / invalid occurrence拒否
- evidence quoteは位置groundingだけでsemantic matcherとして使わない
- Character `realization_refs`が誤っていてもactual relationでREJECT可能
- proposition observation missing / duplicate / unknown ID拒否
- unknown enum / unknown field拒否
- Provider `accepted=true`等のfinal-decision field拒否
- `corrected_text` / replacement field拒否
- bool-as-int budget拒否
- over-bounded claims / evidence拒否

### Budget / discourse

- actual question <= budget / > budget
- actual new-direction <= budget / > budget
- self-disclosure within / exceeded
- finite punctuation/keyword matcherなし

### Freshness / concurrency

- request後にsource revision advance → stale reject
- goal revision advance → stale reject
- attention revision advance → stale reject
- utterance superseded during Verifier → no Observation/Acceptance commit
- cancellation during Verifier → no Observation/Acceptance commit
- same pair concurrent verification → double acceptanceなし
- slow Verifier中にcurrent playback / Body heartbeat / unrelated input継続
- slow Verifier中にSpeech Performance準備継続
- Verifier REJECTED時speculative audio非Presentation

### Adjacent

- #362 Plan → #330 Utterance → #363 Observation / Acceptance
- same Plan + multiple Character variantsを各pairで独立検証
- #363 ACCEPTEDだけが#348 semantic gate入力になり得る
- #363 REJECTEDから修正文なしのtyped categoryでregenerationへ戻せる

実LLMによるparaphrase、unknown、certainty、degree、extra claimのfalse accept / false reject品質はProject Verificationで確認する。

---

## 22. Design Gateまとめ

- [x] VerifierはObserverでありProvider PASSをAuthorityにしない
- [x] Plan-aware relative semantic relationを採用しV1 exact enum reconstructionを正規形にしない
- [x] Character realization refをsemantic proofにしない
- [x] actual utterance evidenceをexact quote + occurrenceでdeterministically groundする
- [x] REQUIRED / OPTIONAL / FORBIDDENのclosed acceptance
- [x] polarity / certainty / degree / unknown / execution truthのrelative relation
- [x] unsupported semantic extra claimのfail-closed観測
- [x] actual question / new-direction budgetをsemantic observationで検証
- [x] LLM-generated CharacterUtteranceはv1でVerifier必須
- [x] ambiguousなlow-risk skipを禁止
- [x] Provider candidateとimmutable SemanticRelationObservationを分離
- [x] final accept/rejectをRuntime deterministic policyから導出
- [x] rejectionはtyped categoryのみで修正文を生成しない
- [x] post-await live freshness / supersede / cancellation gate
- [x] #331 Performance / speculative TTSとのparallelism
- [x] Verifier ACCEPTEDだけではPresentation Authorityにならない

このDesign Gate完了後にのみ#363製造へ進む。
