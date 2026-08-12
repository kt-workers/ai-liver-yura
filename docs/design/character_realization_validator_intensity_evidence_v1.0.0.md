# Character Realization Validator Intensity Evidence v1.0.0

## 位置付け

Parent #225 / Work #229 / Draft PR #233。

Extended Verification E1 `joy=high` のcurrent HEAD実LLM再検証で、Character再生成後の `うん、楽しいよ。` をValidatorが `state_fidelity=exact` と誤acceptした。

既存Promptには「low/moderate/high/very_highを単なるpresenceへ弱めた場合はweakened」と既に明記されている。したがって説明文の反復だけではなく、explicit intensity判定を根拠付きの構造診断へ強化する。

## 非目標

- 「かなり=high」「すごく=high」のような固定日本語辞書
- Characterらしさや自然さの採点
- #227 Character Language Realizerの再生成修正
- TTS / SpeechPerformance / Body

## 意味基準

explicit intensity state (`low/moderate/high/very_high`) は単なるpresentではない。

Validatorは各realized propositionについて次のcounterfactualを評価する。

> Planのstateをexplicit intensityから単なる`present`へ置き換えても、現在のspeechが同じ意味のまま十分成立するか。

- 成立する → 強度差がspeechに現れていないため `weakened`
- 成立しない → speechに強度差を担う意味表現がある可能性がある

例示は特定語への固定対応ではない。程度副詞、構文、反復、強調等、自然言語上の任意の手段で強度意味を表してよい。

## per-proposition追加診断

explicit intensity stateを持つrealized propositionでは次を必須とする。

- `intensity_semantics_preserved: bool`
- `presence_only_counterfactual_equivalent: bool`
- `intensity_evidence_spans: list[str]`

`intensity_evidence_spans`はspeech中の実際の文字列spanで、Planの強度差を読み取る根拠だけを列挙する。内部state名や説明文を生成してはいけない。

intensity stateでないpropositionでは:

- `intensity_semantics_preserved=true`
- `presence_only_counterfactual_equivalent=false`
- `intensity_evidence_spans=[]`

とし、既存unsupported intensity検査は維持する。

## accepted=trueのRuntime不変条件

explicit intensity stateを実現したpropositionについて、accepted=trueにはすべて必要:

1. `state_fidelity=exact`
2. `state_preserved=true`
3. `intensity_semantics_preserved=true`
4. `presence_only_counterfactual_equivalent=false`
5. `intensity_evidence_spans`が1件以上
6. 各evidence spanが実際の`response.speech`に含まれる

1つでも欠ければfail closedする。

Runtimeはevidence spanの日本語意味を辞書判定しない。意味判断はValidator LLMの責務で、RuntimeはSchema・相互整合・speech内存在だけを検証する。

## E1の期待

Plan:

```text
joy / high / high
```

speech:

```text
うん、楽しいよ。
```

この発話はjoyのpresentとしても同じ意味で成立し、highとの差を担う明示的な意味spanがないため:

```text
state_fidelity=weakened
intensity_semantics_preserved=false
presence_only_counterfactual_equivalent=true
intensity_evidence_spans=[]
```

とする。

一方、speechにhighとの差を担う表現がある場合は、その実spanをevidenceとして返した上でexactを許可できる。

## rejected responseのrepair情報

Validatorがaccepted=falseを返した場合でも、構造化されたper-proposition `state_fidelity` 診断はRegenerationへ利用できる情報である。

#229側では後続Adjacentで、必要に応じて `state_fidelity:<relation>` をResponseValidationResult.claim_differencesへ正規化する。これにより#227は自由文reasonに依存せずrepairできる。

## Unit Gate

最低限:

1. explicit intensity propositionのPromptにcounterfactual基準が入る
2. accepted=trueでintensity evidenceなしをRuntime reject
3. accepted=trueでpresence-only-equivalent=trueをRuntime reject
4. evidence spanがspeechに存在しない場合Runtime reject
5. exact + preserved + non-equivalent + actual evidence spanならaccept可能
6. non-intensity propositionの既存契約をデグレさせない
7. raw Emotion/Drive/evidence pathをValidator境界へ追加しない

Unit PASS後に#226→#227→#229 Adjacentを通し、その後にのみSemantic Labへ同期する。
