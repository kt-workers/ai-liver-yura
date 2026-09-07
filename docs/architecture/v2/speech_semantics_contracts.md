# Speech Semantics Authority 型付き契約

## 1. 目的

この文書はIssue #362の実装正本である。Executiveが確定したSpeech intentから「何を伝えるか」を`SpeechSemanticPlan`として確定し、#330 Character Languageへ渡す。最終台詞、語尾、口調、TTS値、Body動作は生成しない。

責務分離はLLM呼出回数を増やすためのものではない。simple pathは信頼済みtyped directiveから決定論的に構成し、complex pathだけがFoundation LLM Roleを使う。両経路は同じcommit gateを通る。

## 2. Authority境界

- #328 ExecutiveはSpeech intent、semantic goal、target、constraint参照を確定する。
- #362 `SpeechSemanticAuthority`はproposition、required / optional / forbidden、polarity、certainty、degree、self-disclosure、question / new-direction budget、execution truth制約を確定する。
- #330 Character Languageは確定Planの意味を変更せず自然言語へ実現する。
- #363 VerifierはPlanとUtteranceの意味関係を観測するだけでPlanを書き換えない。
- #329 Execution AuthorityだけがActual Execution Factを所有する。発話計画は実行完了を主張しない。

Character Profile、raw Emotion / Desire / Drive、raw Execution payload、自然言語辞書、regexはWhat-to-say Authorityにならない。

## 3. 入力snapshot

`SpeechSemanticContextSnapshot`は次をimmutableに保持する。

- committed Executive decision IDとSpeech `ExecutiveIntent`
- source Event IDsとFoundation `RevisionVector`
- bounded `SpeechSemanticFact`
- authoritative `SpeechTruthConstraint`
- intentが参照できるconstraint IDs
- optional `DeterministicSpeechDirective`
- captured timestamp

Speech intentの`semantic_goal_ref`、`target_ref`、`constraint_refs`はsnapshot内のfact / constraintへgroundする。snapshot外参照、別decisionのintent、Speech以外のintentを拒否する。

`SpeechSemanticFact`はfact ID、subject、predicate、strict JSON value、evidence refsを持つ。Factは発話候補ではなくbounded truth/contextであり、Planのpropositionは使用したfact IDsを明示する。

## 4. Plan契約

`SpeechProposition`は次を持つ。

- proposition ID
- subject ref / predicate / strict JSON object
- typed claim kindと、Execution claimの場合のFoundation `ExecutionStatus`
- `REQUIRED / OPTIONAL / FORBIDDEN`
- `AFFIRM / NEGATE / UNKNOWN`
- `CERTAIN / LIKELY / UNCERTAIN / UNKNOWN`
- optional finite degree `[0, 1]`
- bounded evidence fact refs

`SpeechSemanticPlan`はpropositionのほか、self-disclosure policy、question budget、new-direction budget、truth constraint refs、relationship / discourse constraint refsを持つ。

required / optional / forbiddenはproposition IDの別配列へ重複管理せず、各propositionのtyped dispositionを正本にする。Planは最終台詞、固定phrase、SSML、TTS parameter、Body joint、Execution completion factを持たない。

Execution claimかどうかをpredicate文字列、prefix、keyword、regexで分類しない。Fact / Proposition双方のtyped claim kindと`ExecutionStatus`だけをAuthorityにする。degreeは専用fieldだけを正本とし、JSON value内の同名fieldによる二重表現を拒否する。

public callerはcommitted Planをstatus値だけで直接製造できない。LLM / deterministic builderは`SpeechSemanticCandidate`までを作り、Authorityのvalidated commitだけがimmutable Planを構築する。

### 4.1 Communicative material content

What-to-sayは事実命題だけではない。次のような発話行為そのものの意味も、変更・欠落すると伝達意味が変わる場合は`SpeechSemanticPlan`へpropositionとして明示する。

- greeting
- acknowledgement
- gratitude
- apology
- request
- promise / commitment expression
- consent / refusal
- farewell
- その他、Executiveが選択したcommunicative goal

これらを自然言語フレーズの固定辞書で判定しない。

Executive / trusted upstreamが確定したcommunicative semantic goalを、bounded `SpeechSemanticFact`としてsnapshotへ供給する。既存`SpeechSemanticFactKind.DISCOURSE`を使用できる。

## 5. Commit gate

Authorityは次をfail-closedで検証する。

1. candidate identity、decision / intent / source Event identity。
2. source / goal / attention revisionのsnapshot・candidate・current三者一致。
3. requestにfreezeしたsnapshotとcommit対象snapshotの一致。
4. proposition evidence refsがbounded fact IDsの部分集合。
5. intentのsemantic goal / target / constraint refsがsnapshotへground済み。
6. candidate truth constraint refsがExecutive / upstreamのauthoritative集合と完全一致。
7. Executiveが要求するsemantic goal / target / evidenceは、`FORBIDDEN`以外で元Factのsemantic facetが一致するpropositionによって実現する。
8. Executiveのforbidden claimは、`FORBIDDEN`かつ元Factのsemantic facetが一致するpropositionとして保持する。
9. execution truth制約をclosedに照合する。
10. question / new-direction budgetがauthoritative上限以下。
11. forbidden propositionをrequired / optionalとして扱わないtyped schema。
12. 同じplan ID・同じintentの二重commit拒否。
13. D10 `SpeechSemanticBounds` のCandidate上限を満たす。
14. request generationにbindされた`BrainOperationalBoundsPolicy`世代がcommit時にもcurrentである。

LLM candidate自身がtruth constraintやbudgetを空にして安全条件を省略することはできない。Authorityはsnapshotのauthoritative要件を正本にする。

## 6. Simple path

`DeterministicSpeechDirective`がsnapshotにある場合、専用LLMを呼ばずcandidateを構成できる。directiveはtyped propositionとpolicyをすでに持ち、semantic goal / evidence / truth constraintへgroundされる。

simple判定をkeyword / regex / fixed phraseで行わない。typed directiveの存在とpolicyだけで決める。directiveがない、またはcomplex policyがLLMを要求する場合はcomplex pathを使う。

## 7. Complex LLM path

Role IDは`speech_semantics`、schemaはversioned request / candidate schemaとする。requestはsnapshot全体をfreezeし、Provider SDK objectやunbounded text historyを含めない。

LLM outputはstrict field setの`SpeechSemanticCandidate`であり、Authorityを持たない。transport identity、schema、timing、revisionをFoundation `validate_role_exchange()`で検証し、await後にlive ownerからcurrent `RevisionVector`を再取得してcommitする。呼出時revisionをcurrentとして再利用しない。

slow Speech Semantics中もcurrent Speech、Body、Input、unrelated Activityをblockしない。Domain Authority lockにawait、Provider callback、外部I/Oを含めない。

## 8. Failureと後続境界

schema不正、stale、unbounded ref、truth矛盾、budget超過はPlanをcommitしない。free-form Provider例外やpayloadをPlanへコピーしない。

#330は`SpeechSemanticPlan`だけを入力Authorityとして使い、raw Executive contextやraw internal stateを再解釈しない。#363はPlanのproposition IDとactual Character textの意味関係を独立観測する。Character `realization_refs`はalignment hintでありsemantic proofではない。

## 9. D10共有容量方針

Speech Semanticsの技術上限は`BrainOperationalBoundsPolicy.speech_semantics`だけを正本とし、Module固有のmagic numberやsilent clampを持たない。

初期V2上限:

```text
max_facts = 128
max_truth_constraints = 128
max_relationship_constraints = 64
max_discourse_constraints = 64
max_propositions = 64
max_evidence_refs_per_proposition = 16
max_constraint_refs_per_plan = 128
max_question_budget = 16
max_new_direction_budget = 16
max_fact_payload_json_bytes = 16384
```

### 9.1 Snapshot構築

- Executiveの`semantic_goal_ref`、`target_ref`、`evidence_refs`、`forbidden_claim_refs`、truth constraintが参照するFactはrequired集合として先に保持する。
- required Factを128件へ収められない場合、必要Factを切らず`SPEECH_SEMANTIC_CONTEXT_TOO_LARGE`。
- optional Factは`fact kind → fact_id`のstable orderで空き容量に選択する。
- authoritative truth constraintが128件を超える場合はfirst-Nせず`SPEECH_SEMANTIC_CONTEXT_TOO_LARGE`。
- relationship / discourse constraintはCandidate / Directiveのtyped sectionで各64件上限を持つ。入力側の互換`available_constraint_refs` poolは両section合計の技術上限128を超えない。
- Executiveが要求したconstraint refは容量都合で落とさない。
- 各Factの`value`はcanonical JSON UTF-8で16384 bytes以下。超過Factがrequiredならfail-closedし、valueをsubstringや部分objectへ縮めない。

### 9.2 Candidate / Directive

simple deterministic pathとcomplex LLM pathは同じ上限を通す。

- propositions: 64
- evidence refs / proposition: 16
- relationship refs: 64
- discourse refs: 64
- truth + relationship + discourse refs合計: 128
- question budget: 0..16
- new-direction budget: 0..16

authoritative upstream budgetが技術上限16を超える場合は16へclampせずrequestを拒否する。Candidateが上限を超える場合もfirst-NやREQUIRED/FORBIDDEN proposition削除でsuccessにしない。

### 9.3 policy generation freshness

`SpeechSemanticsPolicy`は使用する`BrainOperationalBoundsPolicy`を保持する。request生成時のpolicy generationをProvider await後にcurrent policy generationと照合し、異なる場合は古いresultを新方針へ付け替えずstale rejectする。

Executive decisionに同じ共有policyのprovenanceが存在する場合はgeneration一致を検証する。互換fixture等で別provenanceを使う場合でも、production current-policy Portによるfreshness検証を省略しない。

## 10. 検証

- direct answer / self-disclosure / unknown
- positive / negative / certainty / degree
- required / optional / forbidden
- communicative material content
- question / new-direction budget
- execution truth一致・完了捏造拒否
- snapshot外fact / constraint / target拒否
- deterministic simple pathでLLM未呼出
- complex LLM typed exchange / schema / identity / timing
- source / goal / attentionの各stale reject
- slow complex Role中にunrelated simple pathが完了
- same intent / plan競合commitは高々1件成功
- Fact 128/129、truth constraint 128/129、constraint pool 128/129境界
- Fact payload 16384/16385 byte境界
- proposition 64/65、evidence 16/17境界
- relationship / discourse 64/65、total constraint 128/129境界
- question / new-direction budget 16/17境界
- oversized Provider resultをfirst-N acceptしない
- policy revision変更中のlate LLM resultをreject
