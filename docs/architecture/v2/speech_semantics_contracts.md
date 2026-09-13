# Speech Semantics Authority 型付き契約

## 1. 目的

この文書はIssue #362の実装正本であり、#661のproduction供給契約の設計を含む。Executiveが確定したSpeech intentから「何を伝えるか」を`SpeechSemanticPlan`として確定し、#330 Character Languageへ渡す。最終台詞、語尾、口調、TTS値、Body動作は生成しない。

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

communicative semantic goalの意味定義は#362の不変なcatalogが所有し、Executiveが今回の定義参照を選択する。元Ownerのtyped evidenceと共に#362がbounded `SpeechSemanticFact`へ投影し、既存`SpeechSemanticFactKind.DISCOURSE`を使用する。production供給は第11節に従う。

## 5. Commit gate

Authorityは次をfail-closedで検証する。

1. candidate identity、decision / intent / source Event identity。
2. source / goal / attention revisionのsnapshot・candidate・current三者一致。
3. requestにfreezeしたsnapshotとcommit対象snapshotの一致。
4. proposition evidence refsがbounded fact IDsの部分集合。
5. intentのsemantic goal / target / constraint refsがsnapshotへground済み。
6. candidate truth constraint refsが#362の正規投影でsnapshotへ束縛したauthoritative集合と完全一致。
7. Executiveが要求するsemantic goal / target / evidenceは、`FORBIDDEN`以外で元Factのsemantic facetが一致するpropositionによって実現する。
8. Executiveのforbidden claimは、`FORBIDDEN`かつ元Factのsemantic facetが一致するpropositionとして保持する。
9. execution truth制約をclosedに照合する。
10. question / new-direction budgetがauthoritative上限以下。
11. forbidden propositionをrequired / optionalとして扱わないtyped schema。
12. 同じplan ID・同じintentの二重commit拒否。
13. D10 `SpeechSemanticBounds` のCandidate上限を満たす。
14. request generationにbindされた`BrainOperationalBoundsPolicy`世代がcommit時にもcurrentである。
15. productionでは第11節のsource / projection / meaning / catalog / directive generationと参照解決記録がcommit時にもcurrentである。

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

## 11. production入力の供給契約（#661）

本節は#362 / #430の採用済み意味責務をproductionへ接続する設計である。実装完了を意味しない。#613は以下の公開入口を利用するだけとし、意味判断を再実装しない。

### 11.1 参照選択と元実値の所有者

Executiveはcommitted Speech intentと`semantic_goal_ref`、`target_ref`、`constraint_refs`、`evidence_refs`、`forbidden_claim_refs`を選択する。`ExecutiveFactRef`はExecutiveのbounded read modelであり、`payload`はsnapshotの搬送用である。下流のsemantic projection契約ではない。Speech側がpayloadからsubject / predicate / polarity / certainty / degree / truth ruleを読み取ったり推測したりしてはならない。

現実の事実は元Ownerのpublic typed valueから解決する。`SpeechSemanticContextSourcePort.resolve(ref)`は`fact_id / ExecutiveFactKind / expected revision`で明示登録されたOwnerへ委譲する。IDのprefix、payload内容、自然言語によるroutingは禁止する。参照IDの別名対応が必要なら起動時の明示bindingに保持し、IDを解析して生成しない。

| Executiveの種類 | 元Ownerと公開値 | 識別と現在性 |
|---|---|---|
| `GOAL` | #366 `GoalState` | `goal_id / revision` |
| `COMMITMENT` | #366 `CommitmentState` | `commitment_id / revision` |
| `EXECUTION`、既存productionの`ACTIVITY` | #329 `ActivityExecutionRecord` | `invocation.command.command_id / record_revision`。`result.status`と`effect_uncertainty`を保持 |
| `MEMORY_EVIDENCE` | #332 `MemoryRecord` | `memory_id / revision`。retrieval順位を変更せず、revisionのない`MemoryEvidenceItem`単体をcurrent値の代用にしない |
| `ATTENTION` | #333 `AttentionFocusView` | 登録済みview identityと`revision` |
| `TURN`、`RELATIONSHIP`、その他 | 当該元Ownerのpublic contractを個別に登録 | contract型、identity、revisionの取得規則が登録されていなければ`UNSUPPORTED_SOURCE_CONTRACT`。別Ownerやgeneric JSONで補完しない |

この表は同名kindならすべて意味投影可能という保証ではない。各source contractについて11.4の対応規則が必要である。Goalの寿命を発話行為へ、Memoryの記述を現在の実行完了へ読み替えない。第二Fact Storeは作らず、取得値は要求に束縛されたimmutable snapshotとしてだけ保持する。

`SpeechSemanticSourceBinding`は`executive_fact_id / executive_fact_kind / source_owner / source_contract / source_id / source_revision / typed source value`を持つ。型の識別はpublic contract型の明示登録で行い、generic dictや任意属性探索を使わない。bindingの返却時にOwner・kind・fact ID・元ID・expected revision・型を照合する。元Owner adapterは取得と同一性検証だけを行い、発話上の意味を決めない。

### 11.2 発話行為の定義と選択

`CommunicativeActDefinition`は#362が所有するversioned immutableな意味定義であり、現実の事実ではない。最低限`definition_id / definition_revision / act_kind / semantic_shape / target_requirement / evidence_requirement`を持つ。`act_kind`は型付きの閉じた識別集合とする。greeting / acknowledgement / gratitude / apology / request等の既存§4.1のmaterial contentを表現する。新しい種類は明示した定義・schema更新として追加し、unknownを既知の行為へ丸めない。

`semantic_shape`は必要なpropositionのtyped slot、claim kind、polarity / certainty / degreeの規則、target / evidenceとの束縛規則を持つ。自然言語phraseやkeyword / regexを規則にしない。target requirementは不要・必須の区別と許容するtyped source契約を持つ。evidence requirementは必要なtyped evidence slotと許容するsource/projection種別を持つ。slot数と参照数はD10の既存上限内に収める。0件要件は定義が明示した場合だけ有効で、未登録の救済ではない。

定義群は`CommunicativeGoalCatalog`として#362のMeaningPolicyに所属する。catalog generationはMeaningPolicyの`policy_id / revision`を正本とし、別の可変世代を重複管理しない。definition IDはcatalog内で一意、同一ID・revisionで内容を変更しない。定義の追加・変更・削除はMeaningPolicy revisionを進める。candidate / LLM / #613が稼働中に定義や規則を登録・変更してはならない。

Executiveへは`CommunicativeGoalCatalogView`をboundedなread-only vocabularyとして供給する。viewはcatalog generation、definition ref・revision、選択に必要なtyped shape / target / evidence要件を保持する。全公開定義数をExecutiveの`max_fact_refs`以下とし、超過したcatalogは構築拒否する。黙ってfirst-N選択しない。catalogは実Fact枠と区別するが、要求全体の既存JSON容量上限も維持する。

Executiveはviewにある参照のうち今回採用するactを選択する。#362は今回のact選択、Goal選択、Action選択を行わない。Executiveは定義そのものを生成・変更しない。未知ref、catalog外ref、definition revision不一致、開始時とcurrentのcatalog generation不一致はExecutive commit時に非確定とする。read-only vocabularyの公開はExecutiveのGoal/Action Authorityを奪わない。

### 11.3 semantic goal参照の識別と搬送

意味目標の参照は`UPSTREAM_FACT`と`COMMUNICATIVE_ACT_DEFINITION`のtyped解決結果を持つ。既存`semantic_goal_ref`というID fieldは保持し、そのIDをbounded Fact集合とcatalog集合へexact membership照合する。いずれかexactly oneでなければ拒否する。両集合への衝突は拒否し、prefixで種類を推測しない。

Executiveの確定結果には、選択したSpeech参照の不変な解決記録を束縛する。元snapshotの`ExecutiveFactRef`のID・kind・expected revision、およびcatalog参照のdefinition ID・revision・policy generationを保持する。元Fact payloadを追加Authorityとして複製しない。現行のdecision IDと参照文字列だけからkind/revisionを再推測しない。元snapshotとの照合とcatalog current検査はExecutiveの既存commit境界で行う。

target / evidence / forbidden claimは元typed Factを解決する。constraint参照は、登録済みのtyped制約bindingから元Owner・種類・revisionを解決する。現行Executiveが許容するsource event / capability / precondition等のIDであっても、Speech側に対応するpublic source contractがなければ拒否する。参照文字列の存在だけをSpeech Fact / 制約の存在へ昇格させない。

#362 Context Builderは同じgenerationのdefinitionをresolveし、選択されたactを`SpeechSemanticFact(kind=DISCOURSE)`へ投影する。FactのIDは選択されたsemantic goal refを保持し、definitionのsemantic shapeへtargetとauthoritative evidenceを束縛する。definition revision、policy generation、selected definition ref、target ref、使用したevidence refsを由来へ保持する。

例えばgratitudeの意味定義は#362、ユーザーが助けたという現実の事実は元Owner、今回gratitudeを選ぶ判断と参照選択はExecutiveに属する。定義だけから「助けた」という事実を作らず、必要evidenceがなければ構築を拒否する。上流Factを指すsemantic goalは元typed値の投影であり、catalog definitionへ付け替えない。

### 11.4 Fact投影とtruth rule

`SpeechSemanticFactProjector`とversioned immutableな`SpeechSemanticFactProjectionPolicy`は#362内に置く。規則はsource contractの正確な型とtyped facetに対して明示登録する。各規則は出力するkind / subject / predicate / valueの構造、claim kind / execution status / polarity / certainty / degree、evidence参照の搬送を一意に定義する。登録済み規則が0件・複数一致なら`UNSUPPORTED_PROJECTION`。汎用JSONの意味分類、predicate解析、未知値へのAFFIRM/CERTAIN補完は禁止する。public型内部にJSONがあっても、未宣言fieldの意味を再解釈しない。

Executionの対応規則は#329 `ActivityExecutionRecord.result.status`を`SemanticClaimKind.EXECUTION_STATUS / execution_status`へ保持する。subjectはcommand ID、predicateは規則が定義する状態属性とし、statusという観測済み属性と外部effectの成否を混同しない。`effect_uncertainty`のある失敗・取消・timeoutを「何も起きなかった」というNEGATEへ変換しない。意味規則がそのuncertaintyを表現できなければ拒否する。#613はcompletion claim可否を判断しない。

`SpeechTruthConstraintProjectionPolicy`はFactProjectionPolicyに束縛した不変な規則集合とし、そのgenerationで追跡する。入力は`SpeechSemanticFactKind / SemanticClaimKind / ExecutionStatus / SemanticPolarity / SemanticCertainty`等のtyped facetだけとする。サポートするfacetの組合せごとに次の意味を明示登録する。

- `REQUIRE_MATCH`は既知の元Factとの完全facet一致を要求する規則である。規則未登録のfallbackにはしない。
- `PRESERVE_UNKNOWN`はpolarityとcertaintyの双方がUNKNOWNであるFactにのみ適用し、未知を保持する。片方だけUNKNOWNの値を勝手に両方UNKNOWNへ変えない。
- `FORBID_COMPLETION_CLAIM`は非COMPLETEDのtyped execution statusから完了主張を禁止する。COMPLETEDに対してこの規則を選択しない。実行Factを根拠とするpropositionの元facet一致検査は既存Authorityが別途保持する。

rule selectionの各rowはexact facet条件とruleを持つ。0件・複数一致、ruleの前提とFactの不整合は`TRUTH_RULE_UNRESOLVED`。predicate / payload keyword / regex / 自然言語解釈を使わない。登録された規則集合が既存truth ruleの意味を変えることはできない。constraint IDとfact refの対応を不変に保持する。Executiveが選択したconstraint IDを独自IDへ付け替えず、未解決なら拒否する。

### 11.5 意味方針と技術上限

`SpeechSemanticMeaningPolicy`は`policy_id / revision / self_disclosure_policy / max_question_budget / max_new_direction_budget / communicative_goal_catalog`を保持する#362所有のimmutable方針である。productionの`SpeechSemanticsPolicy`へ明示注入を必須とする。実値は採用された意味方針から供給し、本設計はfixtureのFACT_GROUNDED / 1 / 1をproduction値として採用しない。方針未供給は`SEMANTIC_POLICY_UNAVAILABLE`。

`BrainOperationalBoundsPolicy`は技術的絶対上限だけを所有する。意味方針のbudgetは非負整数であり、技術上限（現在は各16）を超えた場合は起動・構築を拒否する。clampしない。candidate / directiveのbudgetとself-disclosureは、snapshotへ束縛した意味方針と既存Authorityの許容関係を検査する。

### 11.6 provenanceとgeneration

元typed値をFact自身へ埋め込んで型を重複させず、snapshotにFact IDとexactly one対応するimmutable `SpeechSemanticFactProvenance`を並置する。provenanceはsource Owner / contract / ID / revision、projection policy ID / revisionを保持する。communicative definition由来はdefinition ref / revision / MeaningPolicy generationとtarget・evidence参照を追加する。現実のevidenceはそれぞれ別の元Owner bindingへ追跡する。provenance欠落、余剰、重複、不一致は拒否する。JSON payloadだけを由来としない。

`SpeechSemanticContextGeneration`はdecision identity、intent identity、`RevisionVector`、選択済みsource bindingと各source revision、Fact/Truth projection generation、MeaningPolicy/catalog generation、bounds generation、使用するdirective policy generationを束縛する。ポリシーgenerationはIDとrevisionの組であり、同じ組で内容を変更しない。

構築開始・構築完了・simple/LLM準備開始・commit直前に使用した元Ownerのcurrent revisionと各policy generationを照合する。読み取り中に不一致なら`CONTEXT_STALE`で返し、無期限の再試行をしない。LLM await後に要求時の値をcurrentとして再利用しない。ひとつでも変化すれば古い結果を新世代へ付け替えず拒否する。無関係なOwner更新による全体取消は行わない。

最終照合からPlan確定までにはawait / 外部I/Oを入れず、既存Ownerの正規同期境界を用いる。使用するOwner publication/tokenがある場合は既存#632のFenceへ接続し、shadow lockや別Authorityを作らない。元Ownerのcurrent確認を直列化できないbindingはproduction登録を拒否し、取得済みrevisionの比較だけをatomicな最終検査と称さない。既存のparticipant数・順位・容量制約を維持する。

### 11.7 Builderとdeterministic directive

`SpeechSemanticContextBuilder`は#362内で次を行う。

1. `CommittedExecutiveDecision`から対象Speech intentと11.3の確定済み参照解決記録を取得する。
2. semantic goal / target / evidence / forbidden claim / constraintのrequired参照を収集する。
3. 元Ownerのtyped sourceと、選択されたcatalog definitionを同一generationでresolveする。
4. identity / revision / provenanceを照合し、#362の登録済みFact・Truth規則で投影する。
5. 明示注入のMeaningPolicyを束縛し、技術上限と現在性を検査してsnapshotを返す。

required参照を容量都合で落とさない。optional Factは既存D10のkind→fact IDのstable selectionに従う。選択したsourceがunsupportedなら黙って捨てない。失敗時は部分snapshotを成功結果として返さない。

`DeterministicSpeechDirective`を生成できるのは#362だけである。typed Speech intent、projected facts、truth constraints、MeaningPolicy、versioned immutableなdirective policyのみを入力にする。規則はpropositionと各参照・budgetを一意に構成し、同じAuthority gateを通す。規則が存在しなければ`deterministic_directive=None`としてcomplex pathへ進める。存在する規則の不正を「規則なし」に変換しない。keyword / regex / raw Executive payloadからsimple pathを選択しない。

### 11.8 型付き失敗と検証

production構築境界に`SpeechSemanticContextFailureCode`と`SpeechSemanticContextError`を定義する。既存の`SpeechSemanticBoundsError`による容量失敗はこの境界で`CONTEXT_TOO_LARGE`へ型で対応付け、例外文字列で分類しない。LLM役割失敗の契約を複製しない。

| 分類 | 条件 |
|---|---|
| `SOURCE_NOT_FOUND` | 必須source / definitionが見つからない |
| `SOURCE_OWNER_MISMATCH` / `SOURCE_KIND_MISMATCH` / `SOURCE_IDENTITY_MISMATCH` | 元Owner・kind・fact ID・source ID不一致、ID衝突 |
| `SOURCE_REVISION_MISMATCH` | expected source / definition revision不一致 |
| `UNSUPPORTED_SOURCE_CONTRACT` / `UNSUPPORTED_PROJECTION` | public型・current取得境界・投影規則が未対応 |
| `TRUTH_RULE_UNRESOLVED` | truth ruleが一意に決まらない、適用条件不一致 |
| `SEMANTIC_POLICY_UNAVAILABLE` | 明示意味方針がない |
| `SEMANTIC_POLICY_STALE` / `PROJECTION_POLICY_STALE` | 意味/catalog・投影方針の世代変更 |
| `CONTEXT_STALE` | decision / RevisionVector / source / bounds / directive generationの現在性不一致 |
| `CONTEXT_TOO_LARGE` | required集合、payload、catalog、budget等が既存技術上限を超過 |

失敗は安全な識別子と分類で返し、raw source / Provider例外文字列をAuthorityや診断へ流さない。Python外部取消は成功や空snapshotへ変えない。

実装工程ではunit / adjacent試験で、元Owner読取→Builder→simple/complex Planner→Authorityのproduction入口を検証する。catalog内外・ID衝突・definition更新・evidence不足・元Owner不一致・各世代のawait中変更・commit直前変更・source不在・未対応projection・truth未登録・policy未供給・budget超過・required容量超過を含める。#430のcommunicative material content保持と実Execution Factの完了捏造拒否を隣接検証する。tests/Lab fixtureは入力例でありproduction Authorityにはしない。
