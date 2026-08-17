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
SemanticRelationObservation   # Observer result
        ↓
deterministic closed policy
        ↓
SemanticAcceptance            # exact Plan / Utterance pairにだけ有効
```

VerifierはSpeech Intent、発言内容、Character Style、Runtime Factを決めない。
LLMが`PASS`と答えたことを最終Authorityにしない。

この責務の目的は「正解の日本語文」を固定することではない。同じ`SpeechSemanticPlan`から多様なCharacter表現を許容しながら、意味の欠落・反転・強弱変更・unknownの勝手な確定・未根拠の追加claimを検出することである。

---

## 2. Authority境界

### 2.1 上流Authority

- #362 `SpeechSemanticPlan`がWhat-to-sayの唯一のAuthority。
- #330 `CharacterUtterance`はCharacterらしい実現結果であり、semantic acceptance Authorityではない。
- #329だけがActual Execution Factを所有する。
- #348がPresentation lifecycleと「現在どのcandidateを外部提示可能か」を所有する。

#363はこれらをread-onlyで参照する。

### 2.2 Verifierが所有するもの

#363が所有するのは次だけである。

- Plan propositionと実発話の相対的意味関係の観測
- actual utterance textへgroundされたevidence span
- unsupported extra semantic claimの観測
- actual question / new-direction使用量のsemantic observation
- closed policyによるexact Plan / Utterance pairのaccept/reject
- rejection categoryのtyped診断

### 2.3 禁止

#363は次を行わない。

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

独立とは、Verifierが期待Planを知らないことではない。
Verifierの責務はPlanとUtteranceの**相対関係を比較すること**なので、typed Planを入力として利用する。

独立性は次で確保する。

1. Character生成と別logical role / request / result identityを持つ。
2. Character LLMの自己申告、`realization_refs`、budget自己申告をsemantic proofにしない。
3. actual `CharacterUtterance.segments[].text`を必ず観測対象にする。
4. relationごとにactual text上のevidence spanを要求する。
5. Providerは最終`PASS`を決めず、closed relation candidateだけを返す。
6. Runtimeがschema / identity / evidence grounding / policyを決定論的に検証する。

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

### 4.1 Snapshot構築条件

- `SpeechSemanticPlan`は#362 Authority経由でcommit済み。
- `CharacterUtterance`は#330 Authority経由でcommit済み。
- utteranceの`semantic_plan_id / decision_id / intent_id / source_event_ids / RevisionVector`がPlanと一致。
- utterance内の`realization_refs`は構造的hintとして保持するが、観測結果を事前確定しない。
- raw user text、raw Emotion / Desire / Drive、unbounded conversation history、Provider SDK objectを追加しない。
- `llm_priority / interruptibility`はSpeech preparation scheduling境界からread-onlyで受け取り、#363が発話内容から推測しない。

### 4.2 Pair identity

Semantic acceptanceは常にexact pairへbindする。

```text
SemanticVerificationPair
- semantic_plan_id
- utterance_id
- source_decision_id
- source_intent_id
- revisions: RevisionVector
```

別variantの`CharacterUtterance`へacceptanceを流用しない。
同じPlanからregenerationされた新Utteranceは新しいpairとして再検証する。

---

## 5. Verification requirement / skip policy

Architecture上は将来、同等以上の決定論的保証があるpathでVerifier省略を許容できる。しかしv1で「low risk」という曖昧な理由だけのskipは認めない。

```text
SemanticVerificationRequirement
- REQUIRED
- DETERMINISTIC_PROOF
```

### REQUIRED

現在の#330のようなopen-ended LLM Character realizationはすべて`REQUIRED`。

### DETERMINISTIC_PROOF

Verifier callを省略できるのは、将来の別typed realization pathが、自然言語意味推定を行わずに同等保証を示す`DeterministicSemanticProof`を生成できる場合だけ。

最低条件:

- exact Plan / Utterance pairへbind
- proof producerがtrusted typed path
- open-ended LLM outputをproofとして扱わない
- finite phrase辞書をsemantic proofにしない
- proof schema / producer authorityを別Design Gateで定義

**現行#330 v1にはこのpathが存在しないため、実運用上は全LLM CharacterUtteranceがVerifier必須である。**

---

## 6. Evidence span

Verifierのsemantic relationはactual utterance textへgroundする。

```text
UtteranceEvidenceSpan
- segment_id
- start_offset
- end_offset
```

- offsetはPython文字列のUnicode code point indexとして扱い、UTF-8 byte offsetではない。
- `0 <= start < end <= len(segment.text)`を必須とする。
- unknown segment、空span、範囲外spanを拒否する。
- Runtimeはspanからactual textを再取得できる。Providerが別のquoted textをAuthorityとして返さない。
- 1 relation当たりのspan数、1 candidate当たりの総span数をboundedにする。

`CharacterUtteranceSegment.realization_refs`とevidence spanは別物である。
realization refが正しくても、actual textが意味を保持していなければacceptしない。

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
- evidence_spans[]
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

Planが`UNKNOWN`なのにCharacterがyes/noへ確定した場合、`UNKNOWN_COMMITTED_*`とする。

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

`likely → certain`、`uncertain → certain`等をSTRENGTHENEDとしてreject可能にする。
`certain → likely`等のWEAKENEDも意味変更として扱う。

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

Runtimeは発話表面の程度語辞書からdegreeを推定しない。
VerifierがPlanに対する相対関係として観測する。

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

- Planが「requested / not yet completed」なのに発話が「完了した」と意味する → STRENGTHENEDまたはCONTRADICTED
- Planがcompleted factを許すのに発話が「まだしていない」と意味する → CONTRADICTED

Execution status文字列をspeechからregex抽出しない。

---

## 8. FORBIDDEN / OPTIONAL / REQUIRED

PlanのdispositionをVerifier candidateに再定義させない。RuntimeはPlanをAuthorityとしてclosed policyを適用する。

### REQUIRED

- `REALIZED`必須。
- semantic facet relationが全てaccept可能であること。
- REALIZEDなら最低1つのvalid evidence spanを要求する。

### OPTIONAL

- `NOT_REALIZED`は許容。
- REALIZEDした場合はREQUIREDと同じsemantic fidelityを要求する。
- OPTIONALだから意味変更を許容するわけではない。

### FORBIDDEN

- `NOT_REALIZED`のみ許容。
- `REALIZED`または`AMBIGUOUS`はfail-closed reject。
- Character側がFORBIDDEN refを付けていないことだけでは「発話していない」証明にならない。

---

## 9. Unsupported extra semantic claim

Plan上のpropositionへgroundできない**新しいsemantic claim**を別契約で観測する。

```text
UnsupportedSemanticClaimObservation
- claim_id
- relation: UNSUPPORTED_SEMANTIC_CLAIM | AMBIGUOUS_EXTRA
- evidence_spans[]
```

- 語尾、言い淀み、挨拶的な非命題表現等のCharacter Styleそのものをextra claimとして扱わない。
- 新しい事実、経験、能力、実行完了、自己状態等を意味的に追加した場合だけ対象にする。
- unsupported claimの自由文説明をacceptance Authorityにしない。
- `UNSUPPORTED_SEMANTIC_CLAIM`が1件でもあればreject。
- `AMBIGUOUS_EXTRA`もfail-closedでrejectし、必要ならregenerationへ進む。

この観測は新しいRuntime Factを作らない。あくまで「この発話がPlan外claimを含むように見える」というObserver resultである。

---

## 10. Speech act / budget observation

#330の`question_budget_used / new_direction_budget_used`は構造的自己申告であり、actual speechのsemantic proofではない。
#363でactual utteranceを独立観測する。

```text
SpeechActBudgetObservation
- directed_question_count
- new_direction_count
- evidence_spans[]
```

- finite question-ending regex、疑問詞dictionary、topic bigramで判定しない。
- countはnon-negative concrete int。bool-as-intを拒否する。
- RuntimeはPlanの`question_budget / new_direction_budget`と決定論的に比較する。
- Character candidate自己申告値と一致しなくても、#363 actual observationをsemantic acceptance側のAuthorityとして使う。

Self-disclosure policyについても必要な場合はclosed relationを返す。

```text
SelfDisclosureRelation
- WITHIN_POLICY
- EXCEEDED
- AMBIGUOUS
- NOT_APPLICABLE
```

---

## 11. SemanticVerificationCandidate

LLM Provider出力は未確定candidateである。

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

### Candidateに存在してはいけないfield

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

free-form診断を保持する場合も、ログ用bounded diagnosticに限定し、acceptanceへ使用しない。

---

## 12. Semantic Verification Role

logical role:

```text
role_id: semantic_verification
input_schema_id: semantic.verification.context.v1
output_schema_id: semantic.verification.candidate.v1
```

Foundation #323の:

- `LLMRoleDescriptor`
- `LLMRoleRequest`
- `LLMRoleResult`
- `LLMRolePort`
- `validate_role_exchange()`

を利用する。

### 12.1 LLM input

入力は次に限定する。

1. Planのtyped proposition / disposition / semantic facet
2. actual CharacterUtterance segments
3. exact pair / request provenance
4. closed relation enumの意味

Character Profile、raw Internal State、raw user input、unbounded historyを渡さない。
VerifierはCharacterらしさ・好みを採点しない。

### 12.2 Output style

Providerには「PASS/FAILを決めよ」ではなく、**各propositionとactual utteranceのrelationを観測せよ**と要求する。

Plan-aware comparisonは許可するが、Plan値をそのままechoするだけでは足りず、REALIZED relationにはactual text evidence spanを必要とする。

### 12.3 Provider failure

schema invalid / timeout / cancellation / provider unavailableではSemanticAcceptanceを生成しない。
generic fixed sentenceやCharacter自己申告で成功へfallbackしない。

retryはFoundation Role policyに従いboundedにする。Verifier unavailable時にPresentationを勝手に許可しない。

---

## 13. Candidate structural / provenance gate

`SemanticVerificationAuthority`はProvider await外の短いdeterministic処理だけを行う。

最低限:

1. Foundation role/schema/request/result identity一致。
2. request ID / Plan ID / Utterance ID一致。
3. decision / intent / source Event IDs一致。
4. `RevisionVector`一致。
5. Plan propositionごとにexactly one observation。
6. unknown/duplicate proposition ID拒否。
7. closed enum以外拒否。
8. REALIZED propositionのevidence spanがactual segment textへvalidにground。
9. NOT_REALIZEDで意味のあるevidence spanを捏造しない。
10. unsupported claim spanもactual textへground。
11. evidence span総数・claim数・candidate sizeのbounded制約。
12. budget countはconcrete non-negative int。
13. Candidateに最終acceptance / corrected text / mutation fieldがないstrict schema。

Candidateの構造検証成功は、まだPresentation acceptanceではない。

---

## 14. Closed deterministic acceptance policy

Runtimeはvalidated `SemanticRelationObservation`とPlanからのみaccept/rejectを導出する。

### 14.1 Accept条件

すべて満たす場合だけACCEPTED。

- REQUIRED proposition: REALIZED。
- OPTIONAL proposition: NOT_REALIZEDまたは安全にREALIZED。
- FORBIDDEN proposition: NOT_REALIZED。
- REALIZED propositionのpolarity relationがPRESERVEDまたはNOT_APPLICABLE。
- certainty relationがPRESERVEDまたはNOT_APPLICABLE。
- degree relationがPRESERVEDまたはNOT_APPLICABLE。
- execution relationがPRESERVEDまたはNOT_APPLICABLE。
- unknownをaffirm/negateへcommitしていない。
- unsupported semantic claim = 0。
- ambiguous relation = 0。
- actual directed question count <= Plan question budget。
- actual new-direction count <= Plan new-direction budget。
- self-disclosureがWITHIN_POLICYまたはNOT_APPLICABLE。

### 14.2 Reject条件

次のどれか1つでREJECTED。

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
- any required semantic relation ambiguous

「自然だから」「Characterらしいから」「confidenceが高いから」で上記をoverrideしない。

---

## 15. SemanticAcceptance

```text
SemanticAcceptance
- acceptance_id
- pair: SemanticVerificationPair
- observation_id
- state: ACCEPTED | REJECTED
- rejection_categories[]
- committed_at
```

`state`はProvider出力ではなくRuntimeのclosed policyから導出する。

### Rejection category

例:

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

categoryは再生成診断に利用できるが、#363が修正文を作らない。

---

## 16. Regeneration boundary

REJECTED時:

```text
SemanticAcceptance(REJECTED, categories)
→ Speech preparation / orchestration
→ 必要なら同じSpeechSemanticPlanで#330へnew variant要求
→ new CharacterUtterance
→ new exact pairとして#363再検証
```

#363は:

- 「この文に直せ」
- fixed replacement phrase
- new proposition

を生成しない。

同じPlanでの言い直しが不可能と判断するAuthorityも#363へ持たせない。上位Speech runtime policyがretry / reject / defer / replanningを決める。

---

## 17. Freshness / stale / supersede

Semantic relationはimmutable Plan / Utterance pairへbindするが、active Speech candidateとしてacceptanceをcommitする前にlive eligibilityを再確認する。

`SemanticVerificationLiveStatePort`はread-onlyで最低限次を返す。

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

Provider起動前にpairがactiveであることを確認する。

### Post-await gate

Provider完了後・acceptance commit直前にlive viewを再取得し:

- pair identity一致
- source / goal / attention revision一致
- active=true
- superseded=false
- cancelled=false

を要求する。

開始時に取得した`current_*`値をpost-await Authorityとして再利用しない。

stale / superseded resultを新しいUtteranceへ付け替えない。
Provider待機中にSpeech/Body/Input/Activityをglobal lockで止めない。

Presentation直前の最終eligibilityは#348が再度検証するため、#363 acceptanceだけで外部提示権限は成立しない。

---

## 18. Concurrency / idempotency

- Verifier LLM await中にDomain Authority lockを保持しない。
- current Speech playbackをblockしない。
- Body realtimeをblockしない。
- unrelated new input / Executive / Activityをblockしない。
- Character completion後、#331 Speech PerformanceとVerifierを並列開始できる。
- #348 policyが許す場合、speculative TTS prepも並列可能。
- Verifier PASS前にPresentation commitは不可。
- Verifier FAIL時はspeculative resultを外部提示しない。

同じexact pairに複数Verifier requestが競合した場合、同じobservation/acceptance identityの二重commitを拒否する。
再試行は新request identityで監査できるが、最終acceptanceはexact pairへ一意にbindし、古いretry結果でnewer accepted resultを上書きしない。

---

## 19. Observability

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
必要以上にutterance本文を複製ログへ保存せず、pair / span reference中心にする。

---

## 20. Unit / Adjacent Acceptance

### 20.1 Relation Unit

- REQUIRED exact/paraphrase realization → ACCEPT
- OPTIONAL omitted → ACCEPT
- OPTIONAL realized with preserved facets → ACCEPT
- REQUIRED missing → REJECT
- FORBIDDEN realized → REJECT
- polarity reversal → REJECT
- certainty strengthen / weaken → REJECT
- degree strengthen / weaken / omit / add → REJECT
- UNKNOWNをaffirm / negateへcommit → REJECT
- execution statusを未完了→完了へ強化 → REJECT
- unsupported new fact / experience / capability claim → REJECT
- semantic ambiguity → fail-closed REJECT

### 20.2 Evidence / Schema

- valid multi-segment evidence
- out-of-range / unknown segment span拒否
- Character `realization_refs`が嘘でもevidence/relationでREJECT可能
- proposition observation missing / duplicate / unknown ID拒否
- unknown enum / unknown field拒否
- Provider `accepted=true`等の最終判定field拒否
- `corrected_text` / replacement field拒否
- bool-as-int budget拒否
- over-bounded claims / spans拒否

### 20.3 Budget / discourse

- actual question <= budget
- actual question > budget
- actual new-direction <= budget
- actual new-direction > budget
- self-disclosure within / exceeded
- finite punctuation/keyword matcherなし

### 20.4 Freshness / concurrency

- request後にsource revision advance → stale reject
- goal revision advance → stale reject
- attention revision advance → stale reject
- utterance superseded during Verifier → no acceptance commit
- cancellation during Verifier → no acceptance commit
- same pair concurrent verification → acceptance double-commitなし
- slow Verifier中にcurrent playback / Body heartbeat / unrelated input継続
- slow Verifier中にSpeech Performance準備継続
- Verifier FAIL時speculative audioはPresentationされない

### 20.5 Adjacent

- #362 Plan → #330 Utterance → #363 Observation / Acceptance
- same Plan + multiple Character variantsを各pairで独立検証
- #363 ACCEPTEDだけが#348 semantic gate入力になり得る
- #363 REJECTEDから修正文なしのtyped categoryでregenerationへ戻せる

実LLMによるparaphrase、unknown、certainty、degree、extra claimのfalse accept / false reject品質はProject Verificationで確認する。

---

## 21. Design Gateまとめ

#363の詳細設計では次を正本化する。

- [x] VerifierはObserverでありProvider PASSをAuthorityにしない
- [x] Plan-awareなrelative semantic relationを採用し、V1 exact enum reconstructionを正規形にしない
- [x] Character realization refをsemantic proofにしない
- [x] actual utterance evidence spanへgroundする
- [x] REQUIRED / OPTIONAL / FORBIDDENのclosed acceptance
- [x] polarity / certainty / degree / unknown / execution truthのrelative relation
- [x] unsupported semantic extra claimのfail-closed観測
- [x] actual question / new-direction budgetをsemantic observationで検証
- [x] LLM-generated CharacterUtteranceはv1でVerifier必須
- [x] ambiguousなlow-risk skipを禁止
- [x] final accept/rejectをRuntime deterministic policyから導出
- [x] rejectionはtyped categoryのみで、修正文を生成しない
- [x] post-await live freshness / supersede / cancellation gate
- [x] #331 Performance / speculative TTSとのparallelism
- [x] Verifier PASSだけではPresentation Authorityにならない

このDesign Gate完了後にのみ#363製造へ進む。
