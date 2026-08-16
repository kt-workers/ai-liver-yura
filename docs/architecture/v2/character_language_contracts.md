# V2 Character Language Realization Contracts

Owner Issue: #330
Parent: #325
Upstream: #323 / #362 / #355
Downstream: #363 / #331 / #348
Related canonical:
- `docs/architecture/v2/brain_architecture.md`
- `docs/architecture/v2/cognitive_llm_architecture.md`
- `docs/architecture/v2/concurrency_architecture.md`
- `docs/architecture/v2/speech_semantics_contracts.md`
- `docs/architecture/v2/character_projection_contracts.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

#330 Character Language は、#362 が確定した `SpeechSemanticPlan` を、#355 の `CharacterLanguageProfile` に沿った自然言語へ実現する **How-to-say Realizer** である。

```text
SpeechSemanticPlan              # What-to-say Authority
+ CharacterLanguageProfile      # static Character language style
+ bounded language constraints  # relationship / discourse
        ↓
Character Language Role
        ↓
CharacterUtteranceCandidate
        ↓ structural/live gate
CharacterUtterance
        ↓
#363 Independent Semantic Verification
        ↓
#331 / #348 Performance / Presentation
```

#330 は発言内容、事実、Goal、Execution Truthを決めない。
`CharacterUtterance` が生成・構造検証されたことは、意味保持が承認されたことを意味しない。意味保持の独立観測は #363、外部Presentationのacceptanceは #348 が所有する。

---

## 2. Authority boundary

### 2.1 What-to-say Authority

#362 `SpeechSemanticPlan` が唯一の発言意味入力である。

Character Language は次を変更してはならない。

- proposition subject / predicate / value
- REQUIRED / OPTIONAL / FORBIDDEN
- polarity
- certainty
- degree
- execution status / execution truth
- self-disclosure policy
- question budget
- new-direction budget
- truth constraint
- relationship / discourse constraint refs

Characterらしさはこれらを変更する権限ではない。

### 2.2 Character Style Authority

#355 `CharacterLanguageProfile` が static Character Language Style のread-only Authorityである。

利用できるのは `RuntimeAvailability.CONFIRMED` のfacetだけとする。

- `UNRESOLVED` は未確定であり、default値を発明しない。
- `NOT_CONFIGURED` は当該facetを使わない。
- candidate/unknownのauthoring valueをRuntimeへ漏らさない。
- Profile valueをPython側のfixed phrase / sentence-ending dictionaryへ変換しない。
- Character profileを発言事実のsourceにしない。

Profileは語彙、register、距離感、柔らかさ、directness、rhythm、response-length傾向、humor/teasing、hesitation等の**表現傾向**としてのみ使う。

### 2.3 Dynamic state boundary

#330 v1へ raw Emotion / Desire / Drive / Motivation / Relationship state / Activity payload / Execution payload を渡さない。

Dynamic stateやSituationから「何を言うか」を再判断しない。
必要な意味はExecutive → #362 を経て `SpeechSemanticPlan`へ確定済みでなければならない。

### 2.4 Raw text boundary

#330へ次を渡さない。

- raw user text
- raw conversation history
- Characterの過去発話全文をunbounded historyとして渡すこと
- Input Meaningを再解釈するための自然言語本文
- TTS/Voice provider parameter
- Body command / joint / Motion preset

bounded discourse contextが必要な場合は後述するtyped constraint viewだけを使う。

---

## 3. Existing upstream contracts

### 3.1 SpeechSemanticPlan

既存#362契約をそのまま使用する。

```text
SpeechSemanticPlan
- plan_id
- candidate
  - decision_id
  - intent_id
  - source_event_ids[]
  - revisions: RevisionVector
  - propositions[]
  - self_disclosure
  - question_budget
  - new_direction_budget
  - truth_constraint_refs[]
  - relationship_constraint_refs[]
  - discourse_constraint_refs[]
- committed_at
```

`SpeechProposition` のsemantic facetをCharacterが再分類しない。
predicate文字列、keyword、regex、固定markerからpolarity/certainty/execution truthを推測しない。

### 3.2 CharacterLanguageProfile

既存#355契約をそのまま利用する。

```text
CharacterLanguageProfile
- character_id
- schema_version
- definition_revision
- facets[]

RuntimeCharacterFacet
- facet_id
- availability
- value?
- basis_refs[]
```

#330は`CONFIRMED(value)`だけをLLM inputのCharacter Style evidenceへ投影する。
`facet_id`や`value`へCore側の有限反応辞書を持たない。

---

## 4. Bounded relationship / discourse constraint view

`SpeechSemanticPlan`はrelationship/discourse constraintの参照IDを保持するが、ID文字列そのものを意味として解釈してはならない。

#330はtrusted upstream ownerが提供したbounded read-only viewを利用する。

```text
CharacterLanguageConstraintView
- constraint_id
- kind: RELATIONSHIP | DISCOURSE
- source_owner
- source_ref
- source_revision
- language_guidance
```

原則:

- `constraint_id`はPlanの対応refへexactly oneで解決する。
- `language_guidance`はtrusted upstreamが既に確定した表現上の制約であり、#330がraw stateから生成しない。
- constraint ID名、prefix、substringを意味Authorityにしない。
- 同一refが別revision/payloadへ変化した場合はstaleとして再生成する。
- #330はconstraint storeを所有しない。

Relationship constraintは新しいRelationship Factや相手への評価を生成する権限ではない。
Discourse constraintは新しい話題・質問・propositionを追加する権限ではない。

---

## 5. CharacterLanguageContextSnapshot

LLM開始時にimmutable snapshotをfreezeする。

```text
CharacterLanguageContextSnapshot
- request_id
- semantic_plan: SpeechSemanticPlan
- character_profile: CharacterLanguageProfile
- constraints[]: CharacterLanguageConstraintView
- llm_priority: LLMPriority
- interruptibility: LLMInterruptibility
- captured_at
- trace_id
```

Snapshot構築条件:

- `SpeechSemanticPlan`は#362 Authority経由でcommit済みである。
- relationship/discourse refは全件exactly oneでconstraint viewへgroundする。
- constraint kindとPlan上のref categoryが一致する。
- `CharacterLanguageProfile`は1つのcharacter/schema/definition revisionを持つ。
- LLMへ渡すprofile facetはCONFIRMEDだけにfilterする。
- raw Emotion等をsnapshotへ追加しない。
- raw user text / Character history / provider SDK objectを追加しない。

### 5.1 スケジューリングメタデータ

`llm_priority`と`interruptibility`は、commit済みのExecutive Decision又はSpeech preparation scheduling側がrequestごとに確定したread-onlyメタデータを搬送する。

- スケジューリングメタデータはWhat-to-sayでもCharacter Styleでもない。
- `SpeechSemanticPlan`のschemaへpriorityを追加しない。Snapshotを構築するupstream scheduling boundaryが、Planと対応する確定済みmetadataを渡す。
- #330は`purpose`、proposition、raw text、Character Profile又はconstraintからpriority / interruptibilityを推測・再決定しない。
- LLM candidate schemaはpriority / interruptibilityを持たず、これらを書き換えられない。
- `build_request()`はSnapshotの`llm_priority` / `interruptibility`をそのままFoundation `LLMRoleRequest`へ渡す。
- #322のscheduling / backpressure policyが、そのメタデータに基づきforegroundとbackgroundを扱う。#330はglobal queueを所有しない。

Snapshotは入力のcopyであり、新しいsemantic Authorityではない。

---

## 6. Character Language Role

logical role:

```text
role_id: character_language
input_schema_id: character.language.context.v1
output_schema_id: character.language.candidate.v1
```

Foundation #323の:

- `LLMRoleDescriptor`
- `LLMRoleRequest`
- `LLMRoleResult`
- `LLMRolePort`
- `validate_role_exchange`

を利用する。

Provider SDK型、model固有response、Prompt objectをDomain公開境界へ露出しない。

### 6.1 Activation

Character LanguageはSpeechSemanticPlanが存在する場合だけ起動候補になる。
Roleの存在を全Eventでのcall必須条件にしない。

v1のproduction Character realizationで、keyword/regex/fixed phraseによるgeneric fallbackを作らない。
Provider failure時にCharacter未設定の定型文を発明して成功扱いしない。

将来、信頼済みexact-text directive等のdeterministic経路を導入する場合は別typed contractを先に設計する。

### 6.2 Concurrency

- Speech AのPresentation完了をSpeech B Character generationの開始条件にしない。
- Body Motion Planningの完了を待たない。
- Character LLM await中にAuthority lockを保持しない。
- unrelated input / Body / Activity / Speech Presentationをglobal waitさせない。
- same planからのregenerationを可能にし、`1 plan = 1 global Character slot`にしない。
- background requestをFOREGROUNDへ昇格させず、Snapshotから搬送された`LLMPriority` / `LLMInterruptibility`をそのまま利用する。

---

## 7. Strict LLM input

LLM inputは次へ限定する。

1. `SpeechSemanticPlan`のtyped semantic content
2. CONFIRMED `CharacterLanguageProfile` facet
3. bounded relationship/discourse `CharacterLanguageConstraintView`
4. request identity / provenance

PlanのFORBIDDEN propositionも「出してはいけない意味」としてtypedに渡してよいが、実現対象として扱わない。

Character Profile facetはStyleとして明示し、事実claim sourceとして扱わせない。

Prompt implementationは、Profileの文言をそのまま「真実として発言せよ」と指示してはならない。

---

## 8. CharacterUtteranceSegment

Character outputは単一free-form stringだけでなく、後段が参照できる構造を持つ。

```text
CharacterUtteranceSegment
- segment_id
- text
- realization_refs[]       # SpeechProposition ID
- boundary_after
- emphasis
- hesitation
```

### 8.1 boundary_after

engine-independentなlinguistic boundary:

- `CONTINUE`
- `PHRASE`
- `SENTENCE`

これはpause秒数ではない。actual pauseは#331/#358が決める。

### 8.2 emphasis

- `NEUTRAL`
- `EMPHASIZED`
- `DEEMPHASIZED`

これはpitch/volume値ではない。

### 8.3 hesitation

- `NONE`
- `HESITANT`

これは固定fill wordを指定するpresetではない。
実際の言語表現はsegment textに含まれ得るが、finite filler dictionaryをCore Authorityにしない。

### 8.4 realization refs

`realization_refs`は「このsegmentでどのpropositionを実現する意図か」という構造的provenanceであり、意味保持の証明ではない。

- unknown proposition refは禁止。
- FORBIDDEN proposition refは禁止。
- REQUIRED propositionはcandidate全体で最低1回参照する。
- OPTIONAL propositionは0回以上。
- realization refが付いていてもactual textが意味を保持したとはみなさない。#363が独立観測する。

---

## 9. CharacterUtteranceCandidate

LLM resultからstrict parseされる未確定candidate。

```text
CharacterUtteranceCandidate
- candidate_id
- request_id
- semantic_plan_id
- source_decision_id
- source_intent_id
- source_event_ids[]
- revisions: RevisionVector
- character_id
- character_schema_version
- character_definition_revision
- segments[]
- question_budget_used
- new_direction_budget_used
- created_at
```

Candidateは次を所有しない。

- Speech propositionの変更
- truth constraint変更
- Character Definition変更
- Executive Goal/Action変更
- semantic acceptance
- TTS parameter
- Voice performance value
- Body gesture/motion
- Execution Fact

`question_budget_used` / `new_direction_budget_used`はPlanの上限を超えられない。
これらの自己申告だけをactual text意味の証明にしない。#363/#348のsemantic acceptanceが後段に残る。

---

## 10. CharacterUtterance

#330 Authorityのstructural/live validation成功後だけimmutable `CharacterUtterance`を構築する。

```text
CharacterUtterance
- utterance_id
- candidate
- committed_at
```

`CharacterUtterance`のcommit意味は:

> current Plan / Character Profile / constraint provenanceに対して、構造的にgroundされたCharacter表現candidateを生成した。

である。

これは:

- semantic verifier PASS
- Presentation accepted
- speech started/completed

を意味しない。

同じ`SpeechSemanticPlan`から複数variantを生成・commitしてよい。Verifier failureやruntime policyによるregenerationを可能にする。
各variantは一意なcandidate/utterance identityを持つ。

---

## 11. Structural validation

Candidate commit前に最低限次を検証する。

### Identity / provenance

- request/result role/schema identity一致
- request ID一致
- plan ID / decision ID / intent ID一致
- source Event IDs一致
- `RevisionVector`一致
- Character ID/schema/definition revision一致

### Segment structure

- segment ID unique/non-empty
- text non-empty
- segment配列 non-empty
- boundary/emphasis/hesitationはclosed enum
- realization refsはPlan propositionへground
- FORBIDDEN propositionをrealization refにしない
- REQUIRED propositionはcandidate全体でcoverageする

### Semantic budget structure

- `question_budget_used <= plan.question_budget`
- `new_direction_budget_used <= plan.new_direction_budget`
- negative値/bool-as-intを拒否

### Forbidden schema

Candidate schemaへ次のfieldを持ち込まない。

- rewritten proposition
- added fact
- raw Emotion / Desire / Drive
- raw user text
- TTS speed/pitch/volume/speaker
- SSML provider payload
- Body motion / Pose / joint angle
- Execution status claim override

Unknown fieldは黙って無視さずstrict rejectする。

---

## 12. Live commit gate

LLM await後、開始時snapshotをcurrent値として再利用しない。

`CharacterLanguageLiveStatePort`はcommit直前に最低限次をread-onlyで返す。

```text
CharacterLanguageCommitState
- current revisions: RevisionVector
- active_semantic_plan_id / eligibility
- current CharacterLanguageProfile
- current CharacterLanguageConstraintView[]
```

Commit条件:

1. current source/goal/attention revisionsがrequest Planと一致。
2. target `SpeechSemanticPlan`がcurrent speech preparation上でstill eligibleで、superseded/cancelled/staleではない。
3. Character profileのcharacter/schema/definition revisionとimmutable payloadが開始時snapshotと一致。
4. relationship/discourse constraintのID、kind、source owner/ref/revision、payloadが開始時snapshotと一致。
5. Candidate structural validationがPASS。

不一致はtyped stale/superseded/profile-stale/constraint-staleとしてno commit。

Character Profileやconstraintの変更をold generated textへ後付け適用しない。

---

## 13. Semantic preservation boundary

#330はfree-form natural languageを生成するため、closed structural validationだけでactual semantic equivalenceを証明できない。

したがって:

```text
SpeechSemanticPlan
+ CharacterUtterance
→ #363 SemanticRelationObservation
→ deterministic acceptance policy
```

を正規後段とする。

重要:

- `realization_refs`はVerifierへのbounded alignment hintでありproofではない。
- #330 Authorityが「required refsが全部あるから意味保持PASS」と判定しない。
- Character LLM自身の`accepted=true`等をsemantic Authorityにしない。
- required verifier policy下では#363 PASS前にPresentationへcommitしない。

---

## 14. Character variation

Characterらしいvariationは許可し、むしろ期待する。

同じPlan/Profileでも:

- 語順
- 語彙
- rhythm
- phrase segmentation
- 軽いhesitation
- Characterらしいsoftness/directness/humor

は変化してよい。

ただしvariationで次を変えない。

- proposition meaning
- required/forbidden
- polarity/certainty/degree
- execution truth
- question/new-direction budget

固定sentence-ending list、固定reaction phrase、template slot置換だけをCharacter Realizerの主経路にしない。

---

## 15. Character content unresolved behavior

#354 Human Verificationが継続していても#330 mechanismをblockしない。

- CONFIRMED language facetだけ利用する。
- UNRESOLVED/NOT_CONFIGUREDを推測補完しない。
- Profile facetが一部未確定でも、利用可能なCONFIRMED facetだけで生成可能。
- CharacterLanguageProfile自体が利用不能な場合はtyped unavailable/failureとし、#330が「無難なゆら口調」をハードコードしない。

Character contentの具体値変更は#354/#355のdefinition revision更新で反映し、#330 Core algorithm変更を原則要求しない。

---

## 16. Failure behavior

### Provider / schema failure

- typed LLM failure
- no CharacterUtterance commit
- fixed generic responseを成功扱いしない

### Stale semantic plan

- no commit
- old textをlatest planへ付け替えない

### Character profile change

- no commit
- new profileで再生成

### Constraint change

- no commit
- new bounded constraint viewで再生成

### Semantic verifier failure

- #330生成自体をActual Speech failureとはみなさない
- #348 policyがregenerate/reject/supersedeを決める
- same Planから別variantを再生成可能

---

## 17. Non-blocking runtime

- Character LLM timeoutでcurrent playbackを停止しない。
- Body realtimeを停止しない。
- Body Motion Planningを待たない/待たせない。
- Character generation中にもnew input / Appraisal / Executiveは進行可能。
- atomic validation区間へawait / Provider callbackを含めない。
- background Character generationがforeground speechをstarveしないよう#322 scheduling policyを利用する。
- #330はSnapshotの信頼済みスケジューリングメタデータをFoundation requestへ伝播するだけであり、background / foregroundを意味内容やCharacter Styleから判定しない。

Character module自身がglobal queue/schedulerを再実装しない。

---

## 18. Observability

最低限:

- request_id
- semantic_plan_id
- candidate / utterance ID
- character_id / definition_revision
- source/goal/attention revision
- role queued/started/completed/cancelled/stale
- provider latency / failure class
- regeneration count
- downstream verifier result ref when available

Prompt本文、Character Bible全文、secretをmetricsへ記録しない。

---

## 19. Required tests

### Domain / schema

- valid CharacterUtterance segment/candidate
- empty text reject
- duplicate segment ID reject
- unknown enum / unknown field reject
- unknown proposition ref reject
- FORBIDDEN realization ref reject
- REQUIRED proposition coverage必須
- OPTIONAL proposition省略可
- question/new-direction budget境界
- negative/bool budget reject
- TTS/Body/Execution override field不存在

### Character profile

- CONFIRMED facetのみLLM inputへ入る
- UNRESOLVED candidate value leakageなし
- NOT_CONFIGURED default inventなし
- same plan + different confirmed profileでrequest payloadが変わる
- profile definition revision driftでcommit reject
- Character Profileから新しいsemantic propositionを構造上追加できない

### Constraints

- relationship/discourse refsをexactly one resolve
- unknown / duplicate / wrong-kind constraint reject
- constraint source revision/payload driftでcommit reject
- constraint ID文字列のkeyword解釈なし

### Semantic boundary

- candidateはPlan propositionをrewriteしない
- polarity/certainty/degree/execution statusをcandidate schemaでoverrideできない
- realization refsはproof扱いしない
- same Planから複数variant commit可能
- #363向けPlan + Utterance pairを保持

### Freshness

- source_context stale reject
- goal revision stale reject
- attention revision stale reject
- plan superseded/cancelled reject
- Character profile revision drift reject
- constraint revision drift reject

### Scheduling metadata

- `LLMPriority.FOREGROUND`のSnapshotはFOREGROUND requestへそのまま伝播する
- `LLMPriority.BACKGROUND`のSnapshotはBACKGROUND requestへそのまま伝播する
- interruptibilityをそのまま伝播する
- same Planでもupstream scheduling metadata差がLLM request metadataへ反映される
- priority / interruptibilityはcandidate output schemaに存在せず、candidateは書き換えられない

### Concurrency

- fake Character Role delay中にcurrent Speech Presentationが継続
- fake Character Role delay中にBody realtime heartbeatが継続
- Character generationとBody Motion Planningを並列開始可能
- previous Speech playback中にnext Character generation開始可能
- separate speech plan generationをglobal single-slotで直列化しない

### Failure

- provider timeout/errorでgeneric fixed phrase fallbackなし
- invalid schemaでno commit
- stale resultをlatest planへ流用しない

実LLMによる自然さ、variation、Characterらしさ、意味保持品質はcontract tests後にProject `Verification`で確認する。

---

## 20. Non-goals

- SpeechSemanticPlan生成 (#362)
- Semantic equivalence最終判定 (#363)
- acoustic performance / TTS parameter (#331/#358)
- Speech queue / Presentation lifecycle (#348)
- Character Bible内容確定 (#354)
- CharacterDefinition projection (#355)
- Body Gesture/Motion生成 (#337/#338以降)
- raw Emotion/Desire/Drive解釈
- raw user text意味解析
- finite phrase dictionary based Character engine

---

## 21. Design Gate acceptance

#330 implementation開始前に次を満たす。

- 本文書を#330 canonical supplementとしてIssueへ記録する。
- active V2 lineageを`feature/v2-character-language` 1本へ固定する。
- baseはcurrent `rebuild/v2-foundation`と一致する。
- #323 / #362 / #355がcompleted。
- Project #7の#330は`In progress`。
- SpeechSemanticPlan / CharacterLanguageProfile / relationship-discourse constraintのAuthority境界が確定。
- Candidate/Utteranceと#363 semantic acceptanceを分離。
- profile/constraint/live revision gateを確定。
- fixed phrase / regex / raw dynamic state fallbackを禁止。
- exact-head deterministic CI PASS。
- Design Reviewでblocking finding 0。

以後Design → Codeを維持する。
