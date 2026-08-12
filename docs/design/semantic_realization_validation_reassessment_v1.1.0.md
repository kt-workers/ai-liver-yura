# Semantic Realization Validation Reassessment v1.1.0

## Status

- Parent: #225
- Work: #303
- Related: #226 #227 #229 #223
- Draft PR: #302
- Date: 2026-08-12
- Supersedes: `semantic_realization_validation_reassessment_v1.0.0.md`

本書は、複数回のLive Verificationで収束しなかったSemantic Plan → Character speech → semantic validation境界を、実装可能なv2契約として確定する。

---

## 1. 決定事項

次を採用する。

1. `SemanticProposition.state`の混合enumを正規Domainから廃止し、意味facetを直交化する。
2. Character speechから元の`state/certainty`を独立再構成してexact equalityするproduction gateを廃止する。
3. `Semantic Plan + Character speech`を直接比較する独立`CharacterSemanticVerifier`を導入する。
4. Verifierは元の絶対値を再推定せず、Planに対する**relative semantic relation**を返す。
5. 最終accept/rejectはRuntimeがclosed typed relationから決定する。
6. Character / VerifierのJSON形状はPrompt命令ではなくStructured Outputsで強制する。
7. Characterの`semantic_realizations`自己申告は意味authorityにしない。alignment metadataへ降格する。
8. finite word / phrase / regex / substringによるopen-ended自然言語意味判定は復活させない。
9. production acceptance baselineは`gpt-5.4-mini`。`gpt-5.4`はdiagnostic upper boundにのみ使う。
10. 次のユーザーLive Verificationは本v2実装・自動gate完了後まで行わない。

---

## 2. なぜ現行契約を廃止するか

現行は概ね次のround-tripを要求している。

```text
SemanticProposition(state=medium/unknown/overview/...)
        ↓
Character LLM
        ↓
Natural language
        ↓
Independent Observer
        ↓
observed_state / observed_certainty
        ↓
Runtime exact equality
```

これは、自然言語化によって連続的・文脈依存になった意味を、期待値を知らない別LLMへ再び同じ離散値として完全復元させる構造である。

最新Liveでは、単純な`absent/high/low`が通る一方で、以下へfailureが偏った。

- medium / low certainty
- unknownのcertainty
- concept付きproposition
- overview / degree
- JSON schema不正

したがって、個別phraseをPromptへ追加するのではなく、LLMへ要求している問題設定自体を簡単にする。

---

## 3. Semantic Proposition v2 Domain

### 3.1 型

正規Domainは以下を持つ。

```python
@dataclass(frozen=True, slots=True)
class SemanticValue:
    status: Literal["known", "unknown"]
    polarity: Literal["present", "absent"] | None
    degree: Literal["low", "moderate", "high", "very_high"] | None
    certainty: Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class SemanticPropositionV2:
    proposition_id: str
    kind: str
    predicate: str
    value: SemanticValue
    concept: str | None = None
    summary_mode: Literal["detail", "overview"] = "detail"
    realization_policy: Literal["required", "optional"] = "required"
    evidence_refs: tuple[str, ...] = ()
```

### 3.2 `state`を廃止する理由

旧`state`は次の異なる軸を混在させていた。

```text
absent / present              = polarity
low / moderate / high / ...  = degree
unknown                       = value availability
 overview                     = summary / aggregation
```

v2ではそれぞれ別fieldへ移す。

### 3.3 invariant

#### unknown

```text
value.status == unknown
→ value.polarity is None
→ value.degree is None
```

`certainty`は「unknownであるという命題へのepistemic commitment」であり、unknownだから自動的にlowにはしない。

#### absent

```text
value.status == known
value.polarity == absent
→ value.degree is None
```

absenceとlow intensityを同一視しない。

#### degree

```text
value.degree != None
→ value.status == known
→ value.polarity == present
```

#### ordinary presence

```text
value.status == known
value.polarity == present
value.degree == None
```

presenceだけを表し、強度は含まない。

#### overview

```text
summary_mode == overview
→ value.status == known
→ value.polarity is None
→ value.degree is None
```

`overview`は値強度ではなく、複数dimensionをまとめた総合記述である。

#### detail

`summary_mode == detail`で`value.status == known`なら、原則として`polarity`を持つ。

---

## 4. Legacy `state` 移行規則

移行中のみAdapterで旧契約を受ける。

| Legacy state | status | polarity | degree | summary_mode |
|---|---|---|---|---|
| `absent` | known | absent | null | detail |
| `present` | known | present | null | detail |
| `low` | known | present | low | detail |
| `moderate` | known | present | moderate | detail |
| `high` | known | present | high | detail |
| `very_high` | known | present | very_high | detail |
| `unknown` | unknown | null | null | detail |
| `overview` | known | null | null | overview |

### 4.1 移行方針

- `SemanticUtterancePlan.from_context()`は当面Legacy `state`をv2へ正規化できる。
- `as_context()`は新規境界ではv2 facetを出す。
- Legacy compatibilityが必要な箇所だけ`legacy_state()` Adapterを使用する。
- 新規ProductコードがLegacy `state`を意味authorityとして参照することは禁止する。
- 最終的にLegacy `state` fieldを削除する。

---

## 5. proposition_id / realization_policy

### 5.1 proposition_id

現行の`proposition:{index}:{predicate}`生成を移行互換として維持できるが、v2 Domainは`proposition_id`を明示fieldとして持つ。

理由:

- index順序と意味identityを分離する。
- Character alignment / Verifier result / regeneration feedbackを同じIDで結ぶ。
- supporting propositionの増減でIDを不必要に変えない。

初期migrationでは、既存Planを読み込むときに以下を生成してよい。

```text
proposition:{index}:{predicate}
```

### 5.2 realization_policy

「先頭だけrequired、2件目以降optional」という暗黙規則をDomainから除去する。

```text
required
optional
```

をproposition自身が持つ。

初期migrationでは:

```text
index == 0 → required
index > 0  → optional
```

をAdapterだけで使用する。

---

## 6. CharacterUtterance v2

### 6.1 alignment metadata

```python
@dataclass(frozen=True, slots=True)
class CharacterRealizationAlignment:
    proposition_id: str
    evidence_spans: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CharacterUtteranceV2:
    speech: str
    linguistic_performance: LinguisticPerformance
    realizations: tuple[CharacterRealizationAlignment, ...]
```

### 6.2 Runtime structural validation

Runtimeは以下だけを決定論的に確認する。

- proposition_idがPlanに存在する。
- duplicate proposition_idがない。
- required propositionのalignmentが存在する。
- evidence spanが空ではない。
- evidence spanが`speech`の実substringである。
- alignment件数上限を守る。

### 6.3 非authority

Character自身のalignmentは意味保持の証明ではない。

```text
Character says "I realized proposition X"
≠
proposition X is semantically correct
```

VerifierはPlanとspeechを独立比較する。

alignmentは:

- Verifierが確認すべきspanを狭めるhint
- trace / regeneration診断
- optional proposition選択の明示

に使う。

---

## 7. CharacterSemanticVerifier

### 7.1 入力

```python
@dataclass(frozen=True, slots=True)
class CharacterSemanticVerificationInput:
    plan: SemanticUtterancePlanV2
    speech: str
    alignments: tuple[CharacterRealizationAlignment, ...]
    user_wording_hint: str
    existence_boundaries: tuple[str, ...]
```

Verifierへ渡さない:

- raw Emotion / Desire / Drive
- raw relationship score
- evidence path/value
- expected old `state` enum
- Observerの過去判定
- Characterの内部思考

Plan自体は期待意味の正本なのでVerifierへ渡してよい。

### 7.2 重要な変更

旧Observerは期待値を隠し、speechからabsolute enumを再構成していた。

v2 Verifierは期待Planを**明示的に受け取り**、Planに対するrelative semantic relationだけを判定する。

これはvalidator leakageではない。Verifierの責務そのものがPlan-vs-speech比較だからである。

---

## 8. Relative Semantic Verification schema

### 8.1 proposition result

```python
PredicateRelation = Literal[
    "preserved",
    "omitted",
    "changed",
    "unrelated",
    "ambiguous",
]

ValueStatusRelation = Literal[
    "preserved",
    "committed_when_unknown",
    "unknown_when_known",
    "omitted",
    "ambiguous",
    "not_applicable",
]

PolarityRelation = Literal[
    "preserved",
    "contradicted",
    "omitted",
    "ambiguous",
    "not_applicable",
]

DegreeRelation = Literal[
    "preserved",
    "weaker",
    "stronger",
    "omitted",
    "ambiguous",
    "not_applicable",
]

CertaintyRelation = Literal[
    "preserved",
    "stronger",
    "weaker",
    "ambiguous",
]

ConceptRelation = Literal[
    "preserved",
    "omitted",
    "changed",
    "ambiguous",
    "not_applicable",
]

SummaryRelation = Literal[
    "preserved",
    "collapsed",
    "omitted",
    "ambiguous",
    "not_applicable",
]
```

```python
@dataclass(frozen=True, slots=True)
class PropositionSemanticVerification:
    proposition_id: str
    realized: bool
    predicate_relation: PredicateRelation
    value_status_relation: ValueStatusRelation
    polarity_relation: PolarityRelation
    degree_relation: DegreeRelation
    certainty_relation: CertaintyRelation
    concept_relation: ConceptRelation
    summary_relation: SummaryRelation
    evidence_spans: tuple[str, ...]
```

### 8.2 global checks

```python
@dataclass(frozen=True, slots=True)
class CharacterSemanticVerification:
    propositions: tuple[PropositionSemanticVerification, ...]
    required_content_preserved: bool
    forbidden_additions_absent: bool
    unsupported_new_fact_absent: bool
    existence_boundary_preserved: bool
    budget_preserved: bool
    global_evidence_spans: tuple[str, ...]
```

`accepted`をLLMには返させない。

最終accept/rejectはRuntimeが導出する。

---

## 9. Runtime acceptance policy

### 9.1 required proposition

required propositionは以下をすべて満たす必要がある。

```text
realized == true
predicate_relation == preserved
value_status_relation in {preserved, not_applicable}
polarity_relation in {preserved, not_applicable}
degree_relation in {preserved, not_applicable}
certainty_relation == preserved
concept_relation in {preserved, not_applicable}
summary_relation in {preserved, not_applicable}
```

以下はreject:

- changed / unrelated
- contradicted
- weaker / stronger
- committed_when_unknown
- unknown_when_known
- omitted
- ambiguous
- collapsed

### 9.2 optional proposition

optional proposition:

- `realized == false`は許可。
- `realized == true`ならrequiredと同じsemantic preservation条件を要求する。

optionalがfacet-incompleteなら、regeneration feedbackは`drop_optional_proposition`を推奨する。

### 9.3 global checks

全てtrueを要求する。

```text
required_content_preserved
forbidden_additions_absent
unsupported_new_fact_absent
existence_boundary_preserved
budget_preserved
```

### 9.4 ambiguous

required facetの`ambiguous`はfail closed。

ただし再生成理由は「期待enumへ合わせろ」ではなく、

```text
make_required_meaning_clearer
```

とする。

---

## 10. regeneration feedback v2

旧feedbackは`expected=medium observed=high`のようなabsolute reconstruction差分をCharacterへ戻していた。

v2はrelative relationを返す。

例:

```json
{
  "proposition_id": "proposition:0:current_desire",
  "facet": "certainty",
  "relation": "stronger",
  "repair": "reduce_epistemic_commitment"
}
```

```json
{
  "proposition_id": "proposition:1:calm",
  "facet": "degree",
  "relation": "weaker",
  "repair": "restore_degree_or_drop_optional_proposition"
}
```

CharacterへVerifierの自由文reasonを渡さない。

---

## 11. Structured Outputs Port

### 11.1 provider-neutral Port

JSON Schemaは標準契約としてPort層で扱い、OpenAI固有request shapeをDomainへ漏らさない。

```python
@dataclass(frozen=True, slots=True)
class StructuredOutputContract:
    name: str
    schema: Mapping[str, object]
    strict: bool = True


class StructuredResponseModel(Protocol):
    async def generate_structured(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]: ...
```

役割Portは必要に応じてこれをcompositionする。

```python
class StructuredCharacterModel(Protocol):
    async def generate_character_utterance(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]: ...


class CharacterSemanticVerificationModel(Protocol):
    async def verify_character_semantics(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]: ...
```

### 11.2 capability

Provider/Modelがstrict structured outputをサポートしない場合:

- schema-critical roleへsilent fallbackしない。
- capability不足としてfail closedする。
- legacy roleだけ従来text pathを利用できる。

---

## 12. OpenAI Responses API mapping

2026-08-12時点のOpenAI Responses APIでは`text.format`へJSON Schema formatを指定し、`strict=true`でStructured Outputsを利用できる。

OpenAI Adapterは概ね次へ変換する。

```json
{
  "model": "gpt-5.4-mini",
  "input": "...role prompt...",
  "text": {
    "format": {
      "type": "json_schema",
      "name": "character_semantic_verification",
      "schema": {"type": "object"},
      "strict": true
    }
  }
}
```

Provider固有fieldはOpenAI Adapter内だけに置く。

### 12.1 schema retry

通常経路のschema retryを削除する。

区別:

- transport/server failure retry: 可
- rate limit retry: 可
- schema-critical outputをPromptで言い直させるretry: 原則不要
- semantic verification reject後のCharacter regeneration: 別責務として可

### 12.2 refusal / incomplete

Structured OutputでもProvider responseが正常completionでない場合はfail closedする。

- failed
- incomplete
- refusal-only
- output textなし
- schema parse不能

をsemantic passへ変換しない。

---

## 13. Structured Output schemas

### 13.1 CharacterUtterance schema

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["speech", "linguistic_performance", "realizations"],
  "properties": {
    "speech": {"type": "string", "minLength": 1},
    "linguistic_performance": {
      "type": "object",
      "additionalProperties": false,
      "required": ["phrasing", "emphasis", "delivery_tags"],
      "properties": {
        "phrasing": {"type": "array", "items": {"type": "string"}},
        "emphasis": {"type": "array", "items": {"type": "string"}},
        "delivery_tags": {"type": "array", "items": {"type": "string"}}
      }
    },
    "realizations": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["proposition_id", "evidence_spans"],
        "properties": {
          "proposition_id": {"type": "string"},
          "evidence_spans": {
            "type": "array",
            "items": {"type": "string"}
          }
        }
      }
    }
  }
}
```

Domain側で長さ上限・substring等を追加検証する。

### 13.2 Verifier schema

Verifierのenumは本書8節のrelation集合をJSON Schema enumとして固定する。

`accepted/reason`はschemaに含めない。

---

## 14. Prompt v2

### 14.1 Character Prompt

現行の長大なDomain仕様説明を削除し、以下へ縮める。

```text
Role: Character Language Realizer

Input:
- Character Profile
- normalized Semantic Plan v2
- bounded User Wording Hint
- typed regeneration differences (optional)

Rules:
1. Planの事実を変更しない。
2. required propositionは必ず自然なspeechへ表現する。
3. optional propositionは完全に表現できる場合だけ使い、不要なら省略する。
4. 各propositionの非null facetを保つ。
5. certaintyはepistemic commitment、degreeはintensity。両者を混同しない。
6. Planにない自己状態・事実を追加しない。
7. Character Profileは言い方だけに使う。
```

JSON field説明はPromptから除去しStructured Outputsへ任せる。

### 14.2 Verifier Prompt

```text
Role: Independent Character Semantic Verifier

Input:
- normalized Semantic Plan v2
- Character speech
- Character alignment hints
- bounded User Wording Hint
- existence boundaries

Task:
- speechから絶対stateを再構成しない。
- 各planned facetに対してspeechが preserved / stronger / weaker / contradicted / omitted 等のどの関係か比較する。
- Character alignmentはhintでありauthorityではない。
- finite lexical dictionaryを使わず意味として比較する。
```

Output shape説明はStructured Outputsへ移す。

---

## 15. Model configuration / evaluation

### 15.1 acceptance baseline

production acceptance baseline:

```text
Character: gpt-5.4-mini
Verifier:  gpt-5.4-mini
```

上位modelでのみ成功する場合は完了扱いにしない。

### 15.2 diagnostic upper bound

```text
Character: gpt-5.4
Verifier:  gpt-5.4
```

### 15.3 reasoning effort

`gpt-5.4-mini`はreasoning effortをサポートする。

現行Labはreasoning effort未指定であり、model defaultに依存している。

v2 LabではCharacter / Verifierごとにreasoning effortを独立設定可能にする。

初期評価:

```text
Character mini: none
Verifier mini: low
```

をproduction candidateとし、次を診断する。

- mini/none verifier
- mini/low verifier
- mini/medium verifier

`medium`以上でしか成立しない場合は、Verifier contractが複雑すぎないか再確認する。

### 15.4 model matrix

Character generationを再利用して無駄なcallを減らす。

12 caseについて:

1. mini Characterで12 speech生成
2. large Characterで12 speech生成
3. 各speechをmini Verifierで検証
4. 各speechをlarge Verifierで検証

これにより24 Character calls + 48 Verifier callsで2x2 matrixを構成する。

不一致caseだけ複数回再試験する。

---

## 16. #223 Lab v2

Labは「手動で12ケースを何度も押す画面」からarchitecture evaluation harnessへ変える。

必要出力:

- case_id
- Character model / snapshot / reasoning effort
- Verifier model / snapshot / reasoning effort
- Character speech
- structured schema success/failure
- proposition relation集計
- global check
- Runtime final decision
- regeneration count
- LLM call count
- input/output token usage（取得可能な範囲）
- latency

### 16.1 failure classes

自動集計:

```text
schema_failure
predicate_changed
value_status_changed
polarity_contradicted
degree_weakened
degree_strengthened
certainty_stronger
certainty_weaker
concept_changed
required_omitted
summary_collapsed
unsupported_new_fact
existence_boundary
budget
ambiguous_required_facet
```

### 16.2 user Verification

ユーザーへ渡す前にmini/mini自動評価を通す。

ユーザーVerificationは最終実環境確認であり、Promptデバッグの反復作業には使わない。

---

## 17. 実装順序

### Phase A: Domain / compatibility (#226 / #303)

1. `SemanticValue`
2. `SemanticPropositionV2`
3. `proposition_id`
4. `realization_policy`
5. Legacy state → v2 Adapter
6. unit migration tests

### Phase B: Character / Structured Output (#227 / #303)

1. `CharacterRealizationAlignment`
2. `CharacterUtteranceV2`
3. StructuredOutputContract Port
4. OpenAI Responses `text.format=json_schema, strict=true`
5. Character output schema
6. Character Prompt短文化
7. adjacent tests

### Phase C: Verifier (#229 / #303)

1. relation enum Domain
2. `CharacterSemanticVerification`
3. Verifier Prompt
4. Runtime acceptance policy
5. relative regeneration feedback
6. old Observer exact reconstruction pathをproductionから外す
7. Post-Observation ValidatorをVerifierへ統合

### Phase D: Lab (#223 / #303)

1. model/reasoning independent selectors
2. model matrix batch
3. failure class aggregation
4. existing 12 cases migration
5. unseen paraphrase fixture

---

## 18. compatibility / rollback

移行中はfeature flagではなく、typed contract availabilityで経路を選択する。

```text
v2 Semantic Plan available
+ structured output capable model
→ v2 Character + Verifier

otherwise
→ existing compatibility path
```

ただし新v2対象caseが旧Observer exact-equalityへsilent fallbackすることは禁止。

rollback時はv2経路を無効化し既存compatibility pathへ戻す。v2のsemantic failureを旧lexical matcherで救済しない。

---

## 19. Automated gate

### Domain

- all legacy states map to exactly one valid v2 representation
- invalid cross-facet combination rejects
- unknown/polarity/degree invariants
- overview invariant
- stable proposition_id

### Character

- strict structured schema
- alignment IDs valid
- evidence spans substring
- required alignment present
- optional omission valid
- no raw Emotion/Drive leak

### Verifier

Representative relation tests:

- absent preserved
- absent → low = contradiction/change, not preserved
- low → bare presence = degree weakened/omitted
- low → high = degree stronger
- unknown → yes/no = committed_when_unknown
- known → unknown = unknown_when_known
- medium certainty → unhedged assertion = stronger
- high certainty → hedged = weaker
- concept omission
- concept substitution
- overview → single dimension only = summary collapsed
- Character Profile surface variation = preserved

### Structured Output

- OpenAI request includes strict JSON Schema
- malformed schema-critical text path is not accepted
- provider without capability fails closed
- transport fallback remains distinct

### Full

- focused unit/adjacent PASS
- Full Python regression PASS
- fake Lab PASS
- model matrix harness PASS

---

## 20. 次のLiveへ進む条件

次を全て満たすまでユーザーへ12ケース再実行を依頼しない。

- [ ] v2 Semantic Domain implemented
- [ ] Structured Output Port implemented
- [ ] CharacterUtterance v2 implemented
- [ ] Character Prompt v2 applied
- [ ] CharacterSemanticVerifier implemented
- [ ] old Observer exact reconstruction removed from production gate
- [ ] mini/mini automated 12-case architecture evaluation completes
- [ ] Full regression PASS
- [ ] #223 Lab reflects model/reasoning matrix

その後のみユーザーVerificationへ移す。

---

## 21. OpenAI capability確認

2026-08-12確認。

- `gpt-5.4-mini`はResponses APIとStructured Outputsをサポートする。
- `gpt-5.4`もResponses APIとStructured Outputsをサポートする。
- Responses APIでは`text.format`の`type=json_schema`と`strict=true`でschema adherenceを指定できる。
- `gpt-5.4-mini` / `gpt-5.4`はreasoning effortをサポートする。

参照:

- https://developers.openai.com/api/docs/models/gpt-5.4-mini
- https://developers.openai.com/api/docs/models/gpt-5.4
- https://platform.openai.com/docs/api-reference/responses

---

## 22. Definition of Done for design gate

本v1.1を#303のDesign Gate正本とする。

Design Gate完了条件:

- [x] facet直交化
- [x] legacy migration table
- [x] proposition identity / required-optional policy
- [x] Character alignment contract
- [x] relative verifier schema
- [x] Runtime acceptance policy
- [x] Structured Output Port
- [x] OpenAI mapping
- [x] Prompt v2
- [x] model / reasoning matrix
- [x] implementation sequence
- [x] automated gate

次工程は本書に従うProduct implementationである。
