# V2 Brain / Speech Operational Bounds Contracts

Owners: #349 / #328 / #366 / #361 / #362 / #330 / #363
Related: `input_gateway_contracts.md`, `executive_authority_contracts.md`, `goal_commitment_state_contracts.md`, `goal_planning_contracts.md`, `speech_semantics_contracts.md`, `character_language_contracts.md`, `semantic_verification_contracts.md`
Design gate: #445 D10
Status: Shared Canonical Supplement / implementation-decidability correction

## 1. 目的

Brain / Speechの各契約が要求する`bounded context / bounded output / bounded evidence`について、件数、文字数、JSON payload量、overflow時の挙動をversioned policyとして固定する。

本書はsemantic priorityやWhat-to-sayを決めない。**必要な意味を容量都合で黙って切り捨てることは禁止**し、ownerが明示的にbounded viewを作れない場合はfail-closed / typed degradationへ閉じる。

## 2. Common strict size rules

- count/revision/codepoint/byte limitはconcrete `int`、bool禁止。
- countは0を許すfieldだけ明示する。それ以外は`>=1`。
- text lengthはUnicode code point数。
- JSON byte sizeはcanonical JSON UTF-8 bytesで測る。
- canonical JSON: UTF-8、sorted keys、compact separators、NaN/Infinity禁止。
- Provider outputが上限を超えた場合、`first N`、末尾slice、文字substringでsilent truncateしてsuccessにしない。
- snapshot構築前のtrusted owner selectionと、Provider output schema boundは別物として扱う。

## 3. BrainOperationalBoundsPolicy

```text
BrainOperationalBoundsPolicy
- policy_id
- policy_revision: non-negative int
- input: InputBounds
- executive: ExecutiveBounds
- goal_context: GoalContextBounds
- planning: PlanningBounds
- speech_semantics: SpeechSemanticBounds
- character_language: CharacterLanguageBounds
- semantic_verification: SemanticVerificationBounds
```

Initial V2 baseline:

```text
policy_id = v2.brain-operational-bounds.default
policy_revision = 1
```

Production Compositionは有効なpolicyを必須注入する。missing/invalid時に各Moduleが独自defaultを使わない。

## 4. Input Gateway bounds — #349

```text
InputBounds
- max_text_codepoints: 32768
- max_payload_json_bytes: 262144        # 256 KiB
- max_session_metadata_json_bytes: 32768
- max_active_sessions_per_source: 64
```

Rules:

- Text/Speech transcriptが`max_text_codepoints`を超える場合、意味が変わり得る途中切断をGatewayが勝手に行わず`INPUT_TEXT_TOO_LARGE`。
- generic payloadが`max_payload_json_bytes`超過なら`INPUT_PAYLOAD_TOO_LARGE`。large image/audio/binaryはraw bytesではなくprovider-neutral artifact referenceを使う。
- session metadata超過はsession admission reject。
- active session数上限では新規STARTをtyped backpressure rejectし、既存sessionを勝手にterminateしない。
- lifecycle/source-state eventはsame payload boundを通る。

## 5. Executive bounds — #328

```text
ExecutiveBounds
- max_source_event_refs: 64
- max_fact_refs: 256
- max_capability_descriptors: 128
- max_precondition_facts: 128
- max_candidate_intents: 16
- max_goal_transitions: 32
- max_commitment_transitions: 32
- max_refs_per_intent: 64
- max_fact_payload_json_bytes: 16384
```

### 5.1 Snapshot selection

Executive snapshot builderはowner-provided relevance/priority/orderを使う。

- source event: current trigger lineage必須分を先に保持し、残りは`occurred_at desc → event_id asc`。
- Goal/Commitment: #366 bounded `GoalContextView`をそのまま使う。
- Memory: #332 ranking resultをそのまま使いExecutiveがhidden rerankしない。
- Capability: current requirement-relevant descriptorsを先に、残りを`capability_type → capability_id → revision desc`のstable order。
- Precondition: current candidate/owner requirementsへreferencedなものを優先し、unreferenced事実をrequired evidenceの代わりにしない。

Authoritative requirementを上限内に収められない場合、required refをdropしてdecisionを作らず`EXECUTIVE_CONTEXT_TOO_LARGE`。

Candidateがintent/transition/ref上限を超える場合はschema/policy violationでno commit。

## 6. Goal / Commitment bounded view — #366

```text
GoalContextBounds
- max_active_goals: 32
- max_suspended_goals: 32
- max_due_or_active_commitments: 64
- max_recently_changed_items: 64
- max_refs_per_goal: 64
- max_refs_per_commitment: 64
```

Selection:

- active Goal: `priority desc → updated_at desc → goal_id asc`。
- suspended Goal: `priority desc → updated_at desc → goal_id asc`。
- due/active Commitment: due condition evaluationがtrusted ownerから期限順を提供できる場合その順、otherwise `priority desc → updated_at desc → commitment_id asc`。free-text due conditionをStoreが解釈して順序付けしない。
- recently changed: `updated_at desc → type canonical enum order → id asc`。

同一Goal/Commitmentが複数sectionへ現れることは許可するが、section内duplicateは禁止。

refs上限を超える既存canonical stateはview作成時にrequired condition/refを黙って切らず`GOAL_CONTEXT_ITEM_TOO_LARGE`。state自体のmutationはしない。

## 7. Goal Planning bounds — #361

```text
PlanningBounds
- max_capability_descriptors: 128
- max_planning_blockers: 64
- max_activity_context_refs: 128
- max_plan_steps: 64
- max_dependencies_per_step: 16
- max_precondition_refs_per_step: 32
- max_completion_refs_per_step: 32
- max_plan_completion_refs: 64
- max_checkpoint_refs: 64
```

Rules:

- Snapshot required planning requirement / blockerがpolicy capacityを超える場合、必要項目をdropせず`PLANNING_CONTEXT_TOO_LARGE`。
- Candidate DAGがstep/dependency/ref上限を超えたらno commit。
- complex Goalが64 stepを超える構造を必要とする場合、LLMが任意に要約して別Goalへ変えず、upstream Executiveへ`REPLAN_REQUIRED/PLAN_TOO_LARGE` evidenceを返す。
- retry上限は各step candidateのtyped fieldかtrusted planning policyから明示され、negative/boolをreject。generic runtime retry backoffは`runtime_operational_numeric_contracts.md`を使う。

## 8. Speech Semantics bounds — #362

```text
SpeechSemanticBounds
- max_facts: 128
- max_truth_constraints: 128
- max_relationship_constraints: 64
- max_discourse_constraints: 64
- max_propositions: 64
- max_evidence_refs_per_proposition: 16
- max_constraint_refs_per_plan: 128
- max_question_budget: 16
- max_new_direction_budget: 16
- max_fact_payload_json_bytes: 16384
```

Rules:

- Executiveのsemantic goal / target / forbidden/truth requirementへ必要なfact/constraintはsnapshotから落とさない。capacity不足なら`SPEECH_SEMANTIC_CONTEXT_TOO_LARGE`。
- planのquestion/new-direction budgetはauthoritative upstream値を保持するが、technical maximumを超える値はinvalid requestとしてrejectする。technical maximumへsilent clampしない。
- Candidate proposition/evidence/ref上限超過はno commit。
- REQUIRED/FORBIDDEN命題をcapacity都合でOPTIONAL化・削除しない。

## 9. Character Language bounds — #330

```text
CharacterLanguageBounds
- max_constraint_views: 128
- max_confirmed_profile_facets: 128
- max_segments: 64
- max_segment_codepoints: 2048
- max_total_utterance_codepoints: 8192
- max_realization_refs_per_segment: 32
```

Rules:

- Planが参照するrelationship/discourse constraintは全件exact grounding必須。上限不足ならCharacter requestを作らない。
- CONFIRMED profile facetが上限を超える場合、profile ownerがruntime projection policyで利用facet集合を明示的にbounded化する。#330が先頭N facetを選ばない。
- Candidate segment textが1 segment / total上限超過ならschema violation。substring truncate禁止。
- proposition coverageを維持できないからといってsegmentを削ってsuccessにしない。
- Plan question/new-direction budgetは#362の値をそのまま使い、#330 technical countとして再定義しない。

## 10. Semantic Verification bounds — #363

```text
SemanticVerificationBounds
- max_blind_units: 128
- max_evidence_refs_per_unit: 16
- max_quote_codepoints: 512
- max_interaction_acts_per_unit: 4
- max_supporting_units_per_proposition: 32
- max_proposition_relations: 64
- max_accounting_entries: 128
```

Rules:

- `max_proposition_relations`は#362 `max_propositions`以上でなければpolicy invalid。
- `max_accounting_entries`は`max_blind_units`以上でなければpolicy invalid。
- actual utteranceのmaterial semantic contentをblind unit上限へ収められないProvider resultを先頭Nでacceptしない。`SEMANTIC_OBSERVATION_TOO_LARGE`としてAcceptance生成なし。
- quoteが長すぎる場合、LLM/Runtimeが意味単位を壊すsubstringへ自動短縮しない。Providerへ再要求する場合は#348 bounded regeneration/retry generationとして行う。
- Role BはPlan proposition全件・blind unit全件をaccountするため、上限がupstream最大値を覆うことをpolicy validationで保証する。

## 11. Cross-policy invariants

Production policy constructorは少なくとも:

```text
semantic_verification.max_proposition_relations >= speech_semantics.max_propositions
semantic_verification.max_accounting_entries >= semantic_verification.max_blind_units
character_language.max_total_utterance_codepoints >= character_language.max_segment_codepoints
planning.max_capability_descriptors <= executive.max_capability_descriptors or explicit larger owner source exists
```

を検証する。

#330/#363が#362最大値を構造的に受けられないpolicy generationを起動しない。

## 12. Policy freshness

各async LLM requestは`BrainOperationalBoundsPolicy.policy_id/revision`をrequest generationへbindする。

- Provider await中にpolicy revisionが変わったold resultをnew boundへ付け替えない。
- owner contractがsame generationとして明示互換としない限りstale/superseded。
- new requestはcurrent policyでsnapshotを再構築する。
- policy revisionをprovenance/traceへ保持する。

## 13. Overflow observability

Typed reason例:

```text
INPUT_TEXT_TOO_LARGE
INPUT_PAYLOAD_TOO_LARGE
EXECUTIVE_CONTEXT_TOO_LARGE
GOAL_CONTEXT_ITEM_TOO_LARGE
PLANNING_CONTEXT_TOO_LARGE
PLAN_TOO_LARGE
SPEECH_SEMANTIC_CONTEXT_TOO_LARGE
CHARACTER_CONTEXT_TOO_LARGE
CHARACTER_OUTPUT_TOO_LARGE
SEMANTIC_OBSERVATION_TOO_LARGE
```

Diagnosticsへraw oversized payload/textをコピーしない。size/countとsafe IDsだけを記録する。

## 14. Required tests

- 全count/byte/codepoint境界: below/equal/above
- bool-as-int reject
- UTF-8 byteとUnicode code pointの区別
- required evidence overflowでsilent truncationなし
- stable Goal/Capability ordering
- Plan DAG 64/65 step境界
- Speech proposition/evidence/budget境界
- Character segment/total codepoint境界
- Verifier A/B上限のcross-policy validation
- Provider oversized outputをfirst-N acceptしない
- policy revision中のlate LLM result stale
- oversized raw contentがdiagnosticへ漏れない


## 15. Communicative catalogの専用容量（#661）

本節は#661のDesign-only追加契約であり、既存policy revision 1の実装済みfieldを変更済みとは扱わない。実装時の初期拡張generationを`policy_id=v2.brain-operational-bounds.default / policy_revision=2`とし、既存数値は保持して以下を追加する。同一generationでfield集合や上限を変更しない。

```text
BrainOperationalBoundsPolicy
- communicative_catalog: CommunicativeCatalogBounds

CommunicativeCatalogBounds
- max_definitions: 64
- max_definition_json_bytes: 4096
- max_catalog_json_bytes: 524288

ExecutiveBounds（既存fieldに追加）
- max_context_json_bytes: 8388608
```

64定義を各4 KiBで表現できる有限の語彙枠とし、view全体には512 KiBを確保する。Executive全体は8 MiBに制限する。これは技術容量の初期値であり、実際に許可するactや意味内容の選択ではない。意味内容は#362 MeaningPolicyが所有する。将来容量を変更する場合は共有boundsの新generationを採用する。

3つのcatalog上限は独立にすべて検査する。definition件数は0..64、上限field自身はboolを除く正のintとする。空catalogは明示提供された利用可能定義0件を意味し、policy欠落の救済ではない。

definitionのbytesは6 field（definition_id / definition_revision / act_kind / semantic_shape / target_requirement / evidence_requirement）を含む完全なserialized objectで測る。viewのbytesはpolicy_id / policy_revision / definitions / bounds_policy_id / bounds_policy_revisionと配列括弧・区切り等を含む完全なobjectで測る。いずれも§2のcanonical JSON UTF-8（sorted keys、compact separators、NaN/Infinity禁止）に従う。Unicode escapeへ変換して文字数とbytesを混同しない。

`max_context_json_bytes`は`executive.context.v2`の完全なserialized snapshotを測る。catalog、Fact payloadに加え、ID・全metadata・他sectionも含む。LLMの既存transport envelopeの上限は別途維持する。requestのinput全体を「各Factだけboundedだからbounded」とみなさない。

実Factとcatalogは別枠であり、Factは既存256件×payload 16384 bytes、catalogは最大524288 bytesである。両枠のpayload最大の合計は4194304 + 524288 = 4718592 bytes（4.5 MiB）。残りのmetadataと他sectionも含めたsnapshot全体を8388608 bytes以下に検査するため、両枠を同時に最大使用しても**受理されるinputは常に8 MiB以下**である。個別上限内でも全体が超える組合せは拒否する。全sectionの個別最大を同時に必ず受理する保証ではない。

source producer、Executive snapshot構築、LLM request生成、Builder利用で上限を検証する。catalog全体やdefinitionが超過した場合、silent truncation / first-N / definition drop / JSON部分切出しは禁止。#362構築では`SpeechSemanticContextError(CONTEXT_TOO_LARGE)`、Executiveでは`ExecutiveContextError(EXECUTIVE_CONTEXT_TOO_LARGE)`へ閉じる。count / measured bytes / configured limitと安全な識別子だけを診断する。

#362 producerと#328 consumerは同じ共有policy実体または同一ID / revision・同一内容の不変値を参照する。viewにもbounds ID / revisionを保持し、MeaningPolicy generationとは別に照合する。producer / consumer間の不一致は構築拒否、要求後の変更はそれぞれの既存stale / CONTEXT_STALE境界で非確定とする。開始値をcurrentとして再利用せず、commit直前にも元Ownerのcurrent bounds generationと照合する。

実装工程では64/65件、4096/4097 bytes、524288/524289 bytes、8388608/8388609 bytes、bool拒否、Unicode bytes、両枠同時最大、個別内・全体超過、producer/consumer世代不一致、await中bounds更新を検証する。

Executive側の上記errorは#661で設計するtyped境界であり、現行コードに存在するという意味ではない。現行の文字列付きValueErrorを解析して分類せず、構築・request境界の容量判定から直接`ExecutiveContextFailureCode.EXECUTIVE_CONTEXT_TOO_LARGE`を持つ`ExecutiveContextError`へ閉じる。分類名は既存canonicalの容量拒否理由を維持する。
