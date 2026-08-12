# Semantic Realization v2 Structured Character Phase B v1.0.0

## Status

- Parent: #225
- Work: #303
- Design gate: PR #302 / `semantic_realization_validation_reassessment_v1.1.0.md`
- Depends on: Phase A / PR #306
- Phase: B — Character / Structured Output
- Date: 2026-08-12

本書はSemantic Realization v2のPhase Bとして、Characterを「意味を判定するLLM」ではなく「確定済みSemantic Planを自然な発話へ実現するLLM」として構造化し、Verifierが後段でPlanとspeechを比較できる追跡情報を返す境界を固定する。

## 1. Phase Bの目的

Phase Bでは以下を実装する。

1. `CharacterRealizationAlignment`
2. `CharacterUtteranceV2`
3. `StructuredOutputContract` / `StructuredResponseModel` Port
4. `StructuredCharacterModel` Port
5. Character output JSON Schema
6. OpenAI Responses Structured Outputs (`text.format.type=json_schema`, `strict=true`)
7. Character Prompt v2
8. Structured Character service
9. unit / adjacent tests

Phase Bでは以下を実装しない。

- Planとspeechの意味関係判定
- Character alignmentをacceptance authorityとして使用
- Runtime accept/reject / regenerationの切替
- 旧Observer / Validator production gateの除去

これらはPhase Cで行う。

## 2. 既存productionとの互換方針

現行productionは次の境界を使用している。

```text
CharacterModel.generate_character_response(Activity) -> str
    ↓
CharacterLlmService.parse(raw JSON)
    ↓
CharacterResponse
```

Phase Bではこの経路を直接置換しない。

新しい境界を加算する。

```text
SemanticUtterancePlanV2
        + CharacterProfile
        + bounded User Wording Hint
        + typed regeneration differences(optional)
                    ↓
StructuredCharacterPromptBuilder
                    ↓
StructuredCharacterModel
  + StructuredOutputContract(character_utterance_v2)
                    ↓
Mapping[str, object]
                    ↓
CharacterUtteranceV2.from_context(...)
                    ↓
structural validation only
```

Phase CでVerifierとRuntime acceptanceが揃った時点でproduction routingをv2へ接続する。

## 3. CharacterRealizationAlignment

```python
@dataclass(frozen=True, slots=True)
class CharacterRealizationAlignment:
    proposition_id: str
    evidence_spans: tuple[str, ...]
```

### invariant

- `proposition_id`は非空。
- `evidence_spans`は1件以上。
- spanは非空。
- 1 alignmentあたり最大8 span。
- `CharacterUtteranceV2`全体でalignmentは最大24件。

alignmentは「Character自身がここで実現したと申告した位置」を示すhintであり、意味保持の証明ではない。

## 4. CharacterUtteranceV2

```python
@dataclass(frozen=True, slots=True)
class CharacterUtteranceV2:
    speech: str
    linguistic_performance: LinguisticPerformance
    realizations: tuple[CharacterRealizationAlignment, ...]
```

Runtime / DomainがPhase Bで決定論的に確認してよいのは構造だけである。

1. speechが非空。
2. realizationの`proposition_id`がPlanに存在する。
3. duplicate `proposition_id`がない。
4. `realization_policy=required`のpropositionにalignmentがある。
5. evidence spanが非空。
6. 各evidence spanが`speech`の実substringである。
7. alignment/span件数上限を守る。

### non-authority

以下をCharacter alignmentだけから判定しない。

- polarity保持
- degree保持
- certainty保持
- concept保持
- summary保持
- unsupported new fact absence
- existence boundary

これらはPhase C `CharacterSemanticVerifier`の責務である。

## 5. Character output schema

Structured Outputsのcanonical schemaはPort/Promptから独立したApplication側定数として提供する。

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

Domainの件数・substring・required alignment invariantはJSON Schemaだけへ依存せず、typed parse後にも検証する。

## 6. Structured Output Port

Provider固有のrequest shapeをDomainへ漏らさない。

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

class StructuredCharacterModel(Protocol):
    async def generate_character_utterance(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]: ...
```

`StructuredOutputContract`はJSON Schemaを標準契約として持つ。OpenAIの`text.format`などProvider固有shapeはAdapterのみが知る。

## 7. OpenAI Responses Adapter

既存`OpenAIResponseGenerator`へadditiveに`generate_structured()`を追加する。

RequestはOpenAI Responses APIの現行契約に従い、以下へ変換する。

```json
{
  "model": "...",
  "input": "...",
  "text": {
    "format": {
      "type": "json_schema",
      "name": "character_utterance_v2",
      "schema": {"...": "..."},
      "strict": true
    }
  }
}
```

### failure policy

Structured pathでは既存のplain-text fallbackを意味値として採用しない。

以下は`StructuredOutputError`としてfail closedする。

- API keyなし
- HTTP/request failure
- response JSON不正
- output textなし
- output textがJSON objectでない
- schema外の出力をtyped Domainへ変換できない

Phase Bはproductionへ未接続なので、このfailure policyで既存Runtimeの可用性を変更しない。

## 8. Character Prompt v2

PromptはSchema説明を持たない。JSON field説明はStructured Outputsへ委譲する。

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

`bounded User Wording Hint`はユーザー入力を意味authorityとして再注入するものではない。最大長を制限し、言い回し・指示対象の曖昧さ解消にのみ使う。

## 9. StructuredCharacterService

Service責務:

1. `SemanticUtterancePlanV2`からpromptを構築。
2. Character schema contractをStructured Character Modelへ渡す。
3. Mappingを`CharacterUtteranceV2.from_context()`へ渡す。
4. Planとのstructural alignmentを検証。
5. 不正なら`CharacterStructuredOutputError`でfail closedする。

Serviceは意味保持を判定しない。

## 10. Character output schema ownership

Schemaは`app/contracts/character_utterance_v2_schema.py`に置く。

- Domain dataclass: `app/domain/character_utterance_v2.py`
- Port: `app/ports/structured_output.py`
- Prompt: `app/prompting/structured_character_prompt_builder.py`
- Application service: `app/application/structured_character_service.py`
- Provider: `app/adapters/llm/openai_response_generator.py`

依存方向:

```text
Domain ← Application → Ports ← Adapters
             ↓
          Prompting
```

Provider schema request shapeをDomainへ逆流させない。

## 11. Rollback

Phase Bは既存`CharacterModel` production pathと並行する加算実装である。

問題発生時はv2 Structured Character参照を削除すれば、Phase Aおよび既存Character pathへ戻せる。

## 12. Automated Gate

最低限以下を固定する。

### Domain

- valid utterance parse
- duplicate proposition_id reject
- unknown proposition_id reject
- required proposition alignment missing reject
- empty evidence reject
- evidence not contained in speech reject
- optional proposition omission accept
- alignment/span limit reject
- malformed context fail closed

### Port / Provider

- contract name/schema/strict validation
- OpenAI request contains `text.format.type=json_schema`
- contract name/schema/strict are preserved
- structured response returns Mapping
- malformed/missing output fails closed
- plain fallback is not accepted as structured result

### Prompt

- normalized Plan v2 is included
- Character Profile is included
- bounded User Wording Hint is truncated
- typed regeneration differences optional
- Prompt does not embed JSON Schema
- Prompt states Character is language realizer, not semantic authority

### Adjacent

- fake StructuredCharacterModel can generate valid `CharacterUtteranceV2`
- schema-valid but structurally inconsistent alignment is rejected by service
- no existing Character production routing is changed

## 13. Phase B完了条件

- [ ] `CharacterRealizationAlignment` implemented
- [ ] `CharacterUtteranceV2` implemented
- [ ] StructuredOutputContract Port implemented
- [ ] OpenAI Responses Structured Outputs implemented
- [ ] Character output schema implemented
- [ ] Character Prompt v2 implemented
- [ ] StructuredCharacterService implemented
- [ ] Unit / Adjacent PASS
- [ ] Full regression PASS
- [ ] existing production Character routing unchanged
