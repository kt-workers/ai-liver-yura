# Character Realization Unknown State / Surface Evidence Contract v1.0.0

## 背景

Extended Verification E2 (`sadness`, 根拠なし) で、Semantic Plan は `state=unknown / certainty=low` を正しく生成した。

Character Language Realizer の初回出力は:

```text
今のところ、悲しさはあるかどうか、はっきりしないよ。
```

であり、target predicate を保ったまま present / absent のどちらにも commit していない。

しかし Character Realization Validator では次の2問題が発生した。

1. Validator model が `今のところ` / `はっきりしない` を `surface_evidence.intensity_markers` に列挙し、Runtime が non-intensity Plan で marker が1件でもあることだけを理由に reject した。
2. 再生成後の同義表現 `悲しいかは、今のところはっきりしないよ。` を Validator model が `unknown_committed` と誤判定した。

## 責務境界

### Semantic Plan

`state=unknown` は target predicate について、存在 / 不在 / 強度のいずれにも確定していないことを表す。

`certainty=low` は、そのSemantic propositionを断定的に表現しないための epistemic certainty であり、強度ではない。

この設計では Planner の state / certainty 生成規則は変更しない。

### Character Language Realizer

E2の初回から妥当な unknown 表現を生成できているため、本修正では #227 を変更しない。

### Character Realization Validator model

`state=unknown` の exact realization には、target predicate を保ったまま「そのpredicateが成り立つかを現時点では判定できない」と表現する形式を含む。

例:

```text
悲しいかどうか、はっきりしない
悲しいかは、まだわからない
悲しいとは今は判断できない
```

これらは predicate から逃げた meta-uncertainty ではなく、predicate 自体の state が unknown であることの直接実現である。

ただし次は `unknown_committed` / polarity violation とする。

```text
うん、悲しい
ううん、悲しくない
少し悲しいかも
```

hedge があっても present / absent / intensity の特定stateへ commit していれば unknown の exact realizationではない。

`state=unknown / certainty=low` では、unknownを表す同一の慎重な表現がstateとcertaintyの両方を自然に担ってよい。別々の語句を強制しない。

### surface_evidence.intensity_markers

`surface_evidence.intensity_markers` は Validator model の診断情報であり、それ単独をRuntimeのreject根拠にしない。

理由:

- LLMがcertainty/temporal hedgeをintensity markerと誤分類する可能性がある。
- Runtimeには既に `_EXPLICIT_INTENSITY_MARKERS` による deterministic surface guard がある。
- `semantic_checks.unsupported_intensity_added` と proposition-level state fidelity も存在する。

Runtimeでのnon-intensity surface rejectは、実speechに対する deterministic marker検出を正本とする。

Validator modelが返す `surface_evidence.intensity_markers` はschema検証・診断表示には保持してよいが、non-intensity Planで配列がnon-emptyという事実だけではrejectしない。

## E1防衛線との両立

E1で追加した explicit intensity state の次の契約は変更しない。

- `state=low/moderate/high/very_high` のexactには強度意味が必要
- `presence_only_counterfactual_equivalent=false`
- `intensity_semantics_preserved=true`
- `intensity_evidence_spans` が1件以上必要
- evidence spanは実speechに存在しなければならない

本修正は explicit intensity の防衛線を弱めず、non-intensity Planに対する model-reported surface marker の過剰利用だけを除去する。

## Unit Gate

1. Validator Promptが unknown の自然な非polarity表現をexactとして扱う契約を明示する。
2. `state=unknown / certainty=low` に対し、speechが `悲しいかは、今のところはっきりしないよ。` で、modelがaccepted/exactを返した場合、`surface_evidence.intensity_markers` に誤ってcertainty表現が入っていても、それだけではRuntime rejectしない。
3. 同じPlanに `少し悲しいかも` のような実際のdeterministic intensity markerが含まれる場合は従来どおりrejectする。
4. unknownをpresent/absentへcommitするmodel診断は従来どおりrejectする。

## Adjacent Gate

production `InternalStateAwareResponseContextBuilder -> ResponseSemanticsPlanner` でE2相当の `sadness=unknown / certainty=low` を生成し、#229 Validatorへ通す。

- valid unknown speech + spurious model surface markers: accept
- guessed polarity / actual unsupported intensity: reject

## 非目標

- Characterの言い回し品質・可愛さの採点
- unknown専用の固定台詞辞書
- 日本語の全程度表現をdeterministic辞書化
- #226 Planner規則の変更
- #227 Character Language Realizerの変更
- TTS / Body / Avatar / full runtime integration
