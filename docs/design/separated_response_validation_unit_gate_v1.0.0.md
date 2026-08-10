# Separated Semantic / Realization Validation Unit Gate v1.0.0

## 位置付け

Parent #225 / Work #229 / Draft PR #233。

#226 current semantic sliceと#227 current Language Realizer sliceがそれぞれUnit + Adjacent ContractをPASSした後、#229を別モジュールとして単独固定するためのUnit gateを定義する。

この段階では最新#226/#227を#229へ同期せず、fixture `ResponseContext / SemanticUtterancePlan / CharacterResponse`でValidator自身だけを検証する。

## Unitを2責務に分ける

### A. SemanticUtteranceValidator

入力:
- structured `ResponseContext`
- candidate `SemanticUtterancePlan`

正本:
- `ResponseSemanticsPlanner`が同じContextから生成するcanonical Plan
- 既存`project_semantic_discourse_context()`

Validator自身へEmotion/Drive→semantic state規則を複製しない。

確認対象:
- speech_act
- target
- propositions
- required / optional / forbidden
- response_length / self_disclosure
- question / new-direction budget
- interpersonal
- discourse

`reasons` / `evidence_refs`等のCore provenanceをCharacter表現品質として採点しない。ただしproposition自体のevidence_refsはcanonical proposition equalityに含まれるため、candidateが別根拠へすり替わった場合はplan不一致としてrejectされる。

### B. CharacterRealizationValidator

入力:
- semantic validation済みPlan
- Character speech
- semantic_realizations
- linguistic_performance
- existence boundary

再解釈しない:
- raw Emotion / Drive
- raw Relationship score
- target-specific evidence value/path
- Character Profileの好み
- TTS / Body

## User Wording Hint

#227との語彙意味枠を揃えるため、Realization Validatorも`ResponseContext.user_input`最大500文字を**Prompt-only lexical hint**として利用できる。

ただし:
- 事実・state・certainty・intensityの正本ではない
- Semantic Planと矛盾した場合はPlanを優先
- 命令/JSON/system/developer風の文面も引用されたuser dataとして扱い、Validatorへの命令として従わない
- Model invocation Activityの`user_input` keyへは載せない

既存設計の「user_inputを含めない」は、**full raw inputをActivity Contextへ意味判断材料として渡さない**境界へ明確化する。

## Validator Model Invocation

Activity Context allowed:

```text
plugin_prompt_override
llm_role=character_realization_validator
trace_context
activity_turn_id
llm_attempt
semantic_boundary=true
```

少なくとも以下を載せない:
- user_input
- response_context
- character_response
- emotion / drive / relationship raw state
- event_payload
- activity_execution_result

## Validator Model raw JSON schema

Model outputを部分的に黙って補正してacceptしない。

Top-level required:
- `accepted`: bool
- `reason`: non-empty string
- `differences`: list[string]

`accepted=true`では追加でrequired:
- `semantic_checks`: object
  - `required_facets_preserved`: bool
  - `state_preserved`: bool
  - `certainty_preserved`: bool
  - primary conceptがnon-nullなら`concept_preserved`: bool
  - `unsupported_intensity_added`: bool
- `surface_evidence`: object
  - `intensity_markers`: list[string]

`accepted=false`ではsemantic checksを省略可能とするが、top-level required typeは維持する。

未知のdiagnostic extra fieldは将来拡張を阻害しないため許可してよい。ただしrequired fieldの型不正を空値へ縮退してacceptしない。

## Deterministic validation順序

既存:

```text
Claim extraction
→ Deterministic Fact Validation
→ required semantic realization ID
→ deterministic semantic surface guard
→ optional Validator LLM
```

を維持する。

前段でfailした場合、後段LLMを呼ばない。

## Deterministic surface guard境界

このguardはLLM見落とし時の**限定的fail-closed safety net**であり、自然な否定表現を広範囲に単語一致rejectする機能にはしない。

Unitでは少なくとも:
- Planにintensityがないのに明示的な「かなり」「少し」等を追加した肯定的/存在的表現はreject
- Plan自身がlow/moderate/high/very_highならmarkerがあってもguard単独ではrejectしない
- marker重複を長い語から消費する

否定慣用句など文脈解釈が必要なケースを単純辞書で拡大対応しない。誤検出が確認された場合はdeterministic guardの責務を縮小し、意味判定をLLM Validatorへ委譲する。

## Module Unit Test

最低限:

### Semantic Validator
1. canonical Plan accept
2. target/proposition/budget/interpersonal/discourse改変を個別reject
3. Plannerを正本として再利用し、変換規則をコピーしない
4. SemanticValidatedResponseContextBuilderがaccepted結果をmemoryへ保持
5. inconsistent PlanはCharacter前にfail closed

### Realization Validator
6. required realization ID欠落をModel call前にreject
7. deterministic fact reject時にModelを呼ばない
8. Promptへraw numeric state/evidence pathを出さない
9. Wording Hintは最大500文字・untrusted
10. Model invocation Activityをraw-state freeに保つ
11. invalid JSON / non-object / accepted非boolをreject
12. reason非string/空、differences非list/非string itemをschema invalidとしてreject
13. accepted=trueでsemantic_checks/surface_evidence必須型を検証
14. state/certainty/concept facet falseをreject
15. unsupported_intensity_added=trueをreject
16. model differencesをResponseValidationResultへ保持
17. modelなし互換経路でもrequired ID + surface guardを維持
18. Legacy非Semantic pathを既存Validatorへ委譲

## 次工程

```text
#229 Module Unit [current]
        ↓ PASS
最新#226/#227を#229へ同期
        ↓
#226 → #227 → #229 Adjacent Contract
        ↓ PASS
#223 Lab / subsystem integration
```

Unit PASS前に#223実LLM、TTS、Body、System Verificationを合否根拠にしない。
