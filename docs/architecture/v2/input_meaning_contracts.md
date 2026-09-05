# V2 Input Meaning実装契約

Status: Issue #326 implementation canonical / Issue #413 live freshness amendment / #445 D10 decidability supplement
Parent: `brain_architecture.md`
Input: `input_gateway_contracts.md`
LLM: `llm_role_contracts.md`

## 1. 責務

Input MeaningはText/STTの自然言語を`StructuredInputMeaning`へ変換する唯一のopen-ended semantic authorityである。Appraisal、Goal、Attention、返答内容、Activity実行を決定しない。下流はraw textを再解釈しない。

## 2. 入出力

入力は#349の`NormalizedInputEvent`とbounded `ReferenceContext`。Text/Speech以外、lifecycle、空の`text`、schema不一致をfail-closedで拒否する。TextとSTT transcriptは同じRoleとschemaを使う。

成功時に確定する意味は不変の`StructuredInputMeaning`であり、speech act、primary intent、expected response、target、entities、references、provided information、negation、hypothetical、temporal relation、confidence、unresolved fieldsを持つ。confirmation、Activity start/stop、internal-state questionはprimary intentのtyped値として表す。

D10以降、commit済み`StructuredInputMeaning`はacceptanceに使用した`acceptance_policy_id / acceptance_policy_revision`もprovenanceとして保持する。policy revisionは意味内容を生成するLLM Authorityではなく、候補を採用・clarificationへ閉じるdeterministic commit policyの世代である。

### 2.1 本番公開結果 — #564

`InputMeaningInterpreter.interpret()`は`InputMeaningInterpretationResult`を返す。
結果は次の不変データであり、`to_dict()`で厳格なJSONへ直列化できる。
識別情報は信頼できる要求から取得し、不正な応答の識別情報で上書きしない。

```text
InputMeaningInterpretationResult
- request_id: str
- trace_id: str
- source_event_id: str
- source_context_revision: int
- role_status: LLMRoleStatus | None
- meaning: StructuredInputMeaning | None
- role_failure: LLMRoleFailure | None
- boundary_failure: InputMeaningBoundaryFailure | None

InputMeaningBoundaryFailure
- code: LLMFailureCode
- message: str
- retryable: bool
```

`meaning / role_failure / boundary_failure`は必ず1つだけ存在する。

- 成功: `role_status = SUCCEEDED`で`meaning`だけを持つ。意味の出典は結果の入力イベント・世代と一致する。
- 検証済みの役割の非成功: 非成功の`role_status`と、受信した正確な`LLMRoleFailure`だけを持つ。`code / message / retryable`を失わず、状態との対応も既存のLLM契約に従う。
- 所有境界の拒否: `boundary_failure`だけを持つ。受信結果を信頼できない検証失敗では`role_status = None`とする。検証済みの成功候補を採用段階で拒否した場合は`SUCCEEDED`を保持する。

利用側は3つの型付き項目を判定し、例外文字列を解析しない。生の`LLMRoleResult`や提供サービスの例外を公開しない。
不正な入力オブジェクト・`build_request()`の事前条件違反はプログラムの誤用として例外を維持する。
Pythonコルーチンの外部取消は`CancelledError`として伝播する。

`commit_result()`は本番の公開実行口ではなく、副作用のない検証・採用補助関数である。
成功時に`StructuredInputMeaning`を返し、決定論的な不正入力に`ValueError`を送出する性質を維持してよい。
公開実行口はその想定される採用拒否を型付き境界失敗として表現し、汎用例外へ情報を落とさない。

## 3. ReferenceContext

`ReferenceContext`はrevision付きbounded snapshotで、recent speech/presentation、Executive decision、Goal/Commitment、Activity/Actual Fact、current topic、Memory evidenceへのtyped referenceを保持する。上限超過、重複ID、future revisionを拒否する。LLMがreferenceを解決できなければ`unresolved_fields`へ残し、clarificationへ閉じる。

## 4. LLM境界

Input Meaning Roleは#323の可変Role契約を使う。requestはsource event/context revision、foreground priority、cancellation、stale policyを運ぶ。Provider名や固定Role番号を持たない。Provider resultはexchange identity/schema/revision/timestampを検証後、Input Meaning所有validatorが厳密なoutput schemaを構築する。

## 5. Acceptance policy / commit policy

Input Meaningのconfidenceや未解決参照をどうcommitするかを実装者のhidden constantへ委ねない。productionはimmutable/versionedな`InputMeaningAcceptancePolicy`を必須とする。

```text
InputMeaningAcceptancePolicy
- policy_id: non-empty stable identity
- policy_revision: non-negative int
- clarification_confidence_threshold: finite float in [0, 1]
- required_resolution_fields_by_intent:
    primary_intent -> unique tuple[field_name]
```

Rules:

- `required_resolution_fields_by_intent`はproductionでsupportする全`primary_intent`をexactly once覆う。解決必須fieldがないintentも空tupleを明示する。
- field名は`StructuredInputMeaning`のclosed schema fieldだけを参照できる。未知fieldはpolicy validation error。
- thresholdはLLM出力・Character文言・raw user textから生成しない。
- `confidence < clarification_confidence_threshold`なら`clarification_required`。**thresholdと等しいconfidenceは、この条件だけを理由にはrejectしない**。
- 対象intentのpolicyが要求するfieldが`unresolved_fields`に含まれる、または必要値がschema上欠落している場合は`clarification_required`。
- Roleがtyped fieldで明示的にclarificationを要求した場合は、confidenceに関係なく`clarification_required`。
- policyにsupport intentのentryがない、policyがinvalid、またはproduction Compositionでpolicyを取得できない場合は意味を推測せずfail-closedで`POLICY_UNAVAILABLE`相当とし、`StructuredInputMeaning`をcommitしない。
- hidden default threshold、intent名に基づくif/else、substringでrequired fieldを推測してはならない。

初期production値そのものはversioned policy dataとしてComposition Rootから注入する。Core algorithmに数値literalを埋め込まない。policy値の変更は`policy_revision`を進める。

commit判定では次を`clarification_required`とする。

- confidenceがcurrent policy threshold未満
- current policyがそのintentに要求するtarget/reference等の必須解決項目が未解決
- Roleが明示的にclarificationを要求

current context revisionとrequest revisionが異なるresult、非success、schema/identity違反はcommitしない。`mark_stale`や`revalidate`であっても本Issueのcommit関数は最新revisionの明示一致を要求する。

### 5.1 post-await live freshness — #413 / D10 policy freshness

LLM request開始時にfreezeした`NormalizedInputEvent` / `ReferenceContext` / `request.revisions.source_context_revision`は、Providerへ渡す入力世代の正本である。acceptanceに使用する`InputMeaningAcceptancePolicy.policy_revision`もrequest generationへbindする。一方、LLM完了後のcommit freshnessを判断する「current source context / policy」は開始時snapshotではなく、commit直前に取得したauthoritative live revisionを正本とする。

本番の`InputMeaningInterpreter`は、応答の交換契約を検証して成功候補が存在する場合だけ、LLM完了後に`InputMeaningLiveContextPort`（名称は実装上同等のtyped read Portでもよい）からimmutableなlive commit stateを取得する。最低限、そのstateは次を持つ。

```text
InputMeaningFreshnessStamp
- source_context_revision
- acceptance_policy_id
- acceptance_policy_revision
```

正規順序は次とする。

```text
入力世代N・採用方針世代Pを固定して要求を構築
→ LLMRolePort.invoke()
→ 応答の識別・交換契約を検証
  → 不正: boundary_failureを返す（現在世代は読まない）
  → 正当な非成功: 正確なrole_failureを返す（現在世代は読まない）
  → 正当なSUCCEEDED:
    → 正本から現在の入力世代・採用方針世代を1回取得
    → 現在世代の一致を検証
    → 要求の固定内容・候補・採用方針を検証
    → 世代N・Pが一致する場合だけ意味を確定して返す
```

非成功の応答も識別検証を先に行う。要求・役割・追跡・世代の不一致があれば、その応答中のサービス不在等の失敗は信頼しない。
`validate_role_exchange()`が返す`SCHEMA_INVALID / POLICY_VIOLATION`等の既存コードを境界失敗へ保持する。
正当な非成功には採用候補がないため、現在世代を取得しない。待機中に入力世代が進んでも、正当な`PROVIDER_UNAVAILABLE`はそのまま返す。
これによりサービス失敗と現在世代取得失敗の優先順位競合を作らない。

成功候補の採用拒否は次の既存コードへ対応付ける。

| 拒否理由 | code |
| --- | --- |
| 現在の入力世代または採用方針世代の不一致 | STALE |
| 候補・出力の構造不正 | SCHEMA_INVALID |
| 要求の固定内容・識別・採用方針契約違反 | POLICY_VIOLATION |
| 正本から現在世代を取得不能 | REJECTED |

境界失敗の説明文は生の例外を含めず、`retryable=False`とする。
古い要求を自動再試行しない。必要なら上流が新しい世代で新要求を作る。
サービス不在への偽装、意味や確認要求の捏造、失敗の成功への書換えは禁止する。
現在世代取得中も`CancelledError`は伝播し、取得不能の結果へ変換しない。

禁止する。

- callerがLLM開始前に取得した`current_source_context_revision`を、await後もcurrent Authorityとして再利用すること
- request後にpolicy revisionが変わったのにold policy generationとしてcommitすること
- stale resultを新しいrevisionへ付け替えること
- old resultを新しい`ReferenceContext`で再解釈・再利用すること
- stale検出後にInput Meaning内部で暗黙retryして新しい意味を補作すること
- live freshness確認のためにCore global lockやLLM待機を含む長時間lockを導入すること

live source revisionまたはpolicy identity/revisionがrequest generationと異なる場合はfail-closedでstale rejectし、`StructuredInputMeaning`を返さない。live read自体が失敗しcurrent generationを確定できない場合もfail-closedとする。必要な再解釈は、上流が新しいevent/context/policy generationに対して新しいrequestとして起動する。

live readからcommitまでの区間に外部awaitやProvider callを挟まない。Input Meaningのcommitはsource context ownerやpolicy ownerをmutationしないため、成功したmeaningにはrequest時の`source_context_revision`とacceptance policy identity/revisionをprovenanceとして保持する。その直後にcontext/policyが進んだ場合は、下流のrevision gateが世代差を観測できるようprovenanceを失わない。

### 5.2 Port / ownership boundary

`InputMeaningLiveContextPort`はread-onlyであり、Input Meaningへsource-context/policy mutation Authorityを与えない。Port実装はcurrent source-context ownerとpolicy ownerからrevision付きsnapshotを読み、Provider SDK型やraw mutable objectをDomainへ露出しない。

source revisionとpolicy revisionを別ownerから読む場合、composition層のversioned composite snapshotまたはbounded version-stabilized readで一貫した組を取得する。stable pairを確立できなければfail-closedにする。これを理由にCore global lockへ拡張しない。

`InputMeaningInterpreter`のproduction APIは、開始時callerが渡す`current_source_context_revision`やpolicy revisionをpost-await freshness Authorityとして要求しない。テスト専用にcommit関数へ明示revisionを渡す場合でも、その関数はpure validatorとして扱い、production orchestrationでは必ずpost-await live readの値を使用する。

## 6. 禁止事項

- keyword、正規表現、substring、固定phrase辞書をsemantic authorityにすること
- raw textを`StructuredInputMeaning`へ残し、下流に再解釈させること
- Vision/Touch/Game等を自然言語へ強制変換すること
- Input MeaningがAppraisal、Internal State、Goal、Attention、Execution Factを変更すること
- LLM自由文やProvider objectをDomain出力にすること
- confidence thresholdやrequired-resolution ruleをhidden constantとして実装すること

## 7. 並行性

Role Portの1 requestだけをawaitし、global lockや直列queueを所有しない。Runtime priority/backpressureは#322が所有する。slow Input Meaningがunrelated laneを停止しないことはFake Portを用いた隣接testで確認する。

post-await live readは当該requestのcommit gateだけに必要な短いreadであり、他requestやunrelated laneをserializeしない。slow Input Meaning request AのProvider待機中に、別laneや別request Bが進行できる構造を維持する。

## 8. 受入条件

- 全公開snapshotがstrict JSON serializableかつimmutable
- Text/STTが同一semantic authorityを通る
- paraphraseはProvider出力に基づき同一typed meaningとして受理できる
- missing target、general reference、negation、hypotheticalを構造化できる
- versioned acceptance policyが全supported intentをclosed mappingで覆う
- policy threshold境界（未満reject / 等値はthreshold理由だけではaccept可能）を検証する
- required resolution fieldのmissing/unresolvedをpolicyどおりclarificationへ閉じる
- policy missing/invalid/unknown intent mappingをfail-closedにする
- policy revision変更中のlate LLM resultをstale rejectする
- low confidence/unresolvedをclarificationへfail-closedにする
- stale、schema違反、非言語eventをcommitしない
- runtime codeにfinite surface matcherを置かない
- Provider SDK import、Appraisal/Goal/Attention判断を持たない
- request revision NでLLM開始後、live source-contextがN+1へ進んだ場合、production `interpret()`経路がold resultをstale rejectする
- request revisionとpost-await live revisionが一致する場合だけ正常commitする
- live revisionを取得できない場合は意味を補作せずfail-closedにする
- stale reject時にold resultをnew revisionへ付け替えない
- post-await live read導入後もslow Input Meaning中にunrelated workが進行できる
