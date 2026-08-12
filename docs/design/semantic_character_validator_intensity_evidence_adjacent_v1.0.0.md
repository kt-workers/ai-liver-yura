# Semantic → Character → Validator Intensity Evidence Adjacent v1.0.0

## 対象

#226 SemanticUtterancePlan → #227 Character Language Realizer → #229 Character Realization Validator。

Extended Verification E1で観測した `joy=high` のfalse acceptを、production Planner出力から3モジュール境界として固定する。

## Production path

```text
InternalStateAwareResponseContextBuilder
→ ResponseSemanticsPlanner
→ SemanticUtterancePlan: joy/high/high
→ CharacterLanguageRealizerService
→ CharacterRealizationValidator
```

## ケース

### A. bare presenceをfalse exactとして返してもRuntime reject

Character speech:

```text
うん、楽しいよ。
```

Validator modelが誤って:

```text
accepted=true
state_fidelity=exact
intensity_semantics_preserved=true
presence_only_counterfactual_equivalent=false
intensity_evidence_spans=[]
```

を返しても、Runtimeは`intensity_evidence_missing`でrejectする。

### B. counterfactual診断を反映してreject

同じbare speechについて:

```text
state_fidelity=weakened
intensity_semantics_preserved=false
presence_only_counterfactual_equivalent=true
```

ならRuntimeはsemantic facet failureとしてrejectする。

### C. 実speech根拠付きexactをaccept

Character speechにhighとの差を担う表現があり、Validatorがその実部分文字列を`intensity_evidence_spans`へ返す場合、他facetがexactならaccept可能。

特定の程度語とhighの固定対応をテストしない。fake Validatorの意味診断とRuntimeの構造契約だけを確認する。

## Boundary

Character / Validator model invocationへ以下を渡さない。

- raw Emotion
- raw Drive
- full ResponseContext
- event payload
- activity execution result

Semantic Planが唯一の意味正本である。

## Gate

本Adjacent PASS後にのみSemantic Labへ同期し、current HEADでE1を実OpenAI再検証する。
