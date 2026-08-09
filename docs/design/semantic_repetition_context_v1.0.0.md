# Semantic Repetition Context v1.0.0

## 目的

Character LLMをLanguage Realizerへ限定した後も、直近発話との不自然な反復を避けられるようにする。

反復回避のためにraw Emotion / Drive / full ResponseContextをCharacterへ戻してはならない。

## 境界

```text
ResponseContext.recent_speech_summary
+ constraints.avoid_repetition
        ↓
SemanticUtterancePlan.discourse_context
        ↓
Character Language Realizer
```

`avoid_repetition=true`かつ`recent_speech_summary`が存在するときだけ、次をSemantic Planへ投影する。

```json
{
  "recent_speech_summary": "直近発話の短い要約",
  "repetition_policy": "avoid_semantic_and_phrasal_repeat"
}
```

## 責務

この情報は「何を新しく主張するか」を決める事実ではなく、確定済みSemantic Planをどのように言語実現するかに必要な談話制約である。

Characterはこれを使って:

- 同一文面の反復を避ける
- 同じ意味を必要以上に同じ言い回しで繰り返さない
- typed targetやsemantic proposition自体は変更しない

## 渡さないもの

反復回避のためであっても次はCharacterへ再露出しない。

- raw Emotion / Desire / Drive
- raw relationship score
- full ResponseContext
- evidence path/value
- Activity execution payload

## 無効時

`avoid_repetition=false`またはrecent speechが空の場合は、recent speechをSemantic Planへ含めない。

## Validator

反復検出そのものは既存Pipelineのdeterministic repetition checkを維持する。

再生成時には同じSemantic Planを保持し、Characterは`discourse_context.recent_speech_summary`を参照して表現だけを変える。

## Verification

- Semantic Planにraw数値を含めない
- `avoid_repetition=true`時だけrecent speechを投影
- Character model boundaryにfull ResponseContextを戻さない
- current feeling repetition presetで同じtyped targetを維持する
- 再生成時に無関係な新話題へ逃げない
