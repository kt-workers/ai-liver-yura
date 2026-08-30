# V2 Input Meaning実装契約

Status: Issue #326 implementation canonical / Issue #413 live freshness amendment / #445 D10 decidability supplement
Parent: `brain_architecture.md`
Input: `input_gateway_contracts.md`
LLM: `llm_role_contracts.md`

## 1. 責務

Input MeaningはText/STTの自然言語を`StructuredInputMeaning`へ変換する唯一のopen-ended semantic authorityである。Appraisal、Goal、Attention、返答内容、Activity実行を決定しない。下流はraw textを再解釈しない。

## 2. 入出力

入力は#349の`NormalizedInputEvent`とbounded `ReferenceContext`。Text/Speech以外、lifecycle、空の`text`、schema不一致をfail-closedで拒否する。TextとSTT transcriptは同じRoleとschemaを使う。

出力はimmutableな`StructuredInputMeaning`であり、speech act、primary intent、expected response、target、entities、references、provided information、negation、hypothetical、temporal relation、confidence、unresolved fieldsを持つ。confirmation、Activity start/stop、internal-state questionはprimary intentのtyped値として表す。

D10以降、commit済み`StructuredInputMeaning`はacceptanceに使用した`acceptance_policy_id / acceptance_policy_revision`もprovenanceとして保持する。policy revisionは意味内容を生成するLLM Authorityではなく、候補を採用・clarificationへ閉じるdeterministic commit policyの世代である。

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

production `InputMeaningInterpreter`は、LLM完了後に`InputMeaningLiveContextPort`（名称は実装上同等のtyped read Portでもよい）からimmutableなlive commit stateを取得する。最低限、そのstateは次を持つ。

```text
InputMeaningFreshnessStamp
- source_context_revision
- acceptance_policy_id
- acceptance_policy_revision
```

正規順序は次とする。

```text
freeze request input at source revision N + policy revision P
→ invoke Input Meaning Role
→ await provider result
→ read authoritative live source revision + acceptance policy revision
→ validate exchange / request snapshot / live revisions
→ apply the same versioned acceptance policy
→ construct StructuredInputMeaning only if live source == N and live policy == P
```

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
