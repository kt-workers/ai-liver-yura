# Character Language Realizer State Fidelity v1.0.0

## 位置付け

Parent #225 / Work #227 / Draft PR #232。

Extended Verificationで、Semantic PlanのstateがCharacter発話で弱化・polarity化・supporting stateの崩れを起こすケースが確認されたため、Character Language Realizerの意味保持境界を追加で固定する。

この設計は台詞品質やCharacterらしさを採点するものではない。Semantic Utterance Planで確定済みの意味を、自然文へ変換するときに保持すべきstate fidelityだけを対象とする。

## 検出された失敗類型

### 1. explicit intensityの弱化

`state=high/moderate/low/very_high` は単なるpresentではない。

例えばPlanが `joy=high` なら、発話はjoyの存在だけでなくhigh相当の強度意味も保持する必要がある。単に「楽しい」「うれしい」とだけ述べ、強度差が失われる場合はstate fidelity不足とする。

固定語辞書は導入しない。強度は自然言語上の程度・強調・構文等で意味的に表現できればよい。

### 2. unknownのpolarity確定

`state=unknown` はpresentでもabsentでもない。

yes/no型質問への応答で、「うん」「ううん」「そう」「違う」等が文脈上の肯定・否定を確定し、その後の本文も特定polarityへ寄せる場合はunknown保持違反とする。

unknownは「判断できていない」「はっきりしない」等、存在・不在・強度を確定しない形で表現する。certainty=low/highはunknownというstateそのものへのepistemic certaintyであり、polarity推測の許可ではない。

### 3. supporting propositionのpartial realization

primary propositionは従来どおり必須。

supporting propositionは省略可能だが、Characterが任意にspeechへ採用し `semantic_realizations` に列挙した場合、そのpropositionのpredicate/state/certainty/conceptを意味的に保持する。

したがって、supporting `joy=high` をspeechへ採用するならjoyの存在だけに弱めない。supporting `calm=low` を「穏やか」とだけ表現してlowを失わない。

supporting propositionを省略すること自体はエラーではない。短い応答制約下で、primaryだけを自然に実現することは許可する。

## Character-facing machine-readable contract

各propositionに以下を投影する。

- `realization_policy`
  - primary: `required`
  - supporting: `optional_but_facet_complete_if_realized`
- `if_realized_required_facets`
  - predicate
  - state
  - certainty
  - concept（non-null時のみ）
- `state_semantics`
  - present: `presence_without_intensity`
  - absent: `absence`
  - unknown: `unknown_without_polarity_guess`
  - low/moderate/high/very_high: `explicit_intensity_state`
- `intensity_fidelity`
  - intensity state: `must_preserve_intensity_if_realized`
  - その他: `not_applicable`
- `polarity_commitment`
  - unknown: `forbidden`
  - その他: `bounded_by_state`

primary用Required Facet Realization Contractにも、explicit intensityをpresenceへ弱めないこととunknownでpolarityを確定しないことを明示する。

## Regeneration Feedback

Validatorが `state_preserved=false` を返した場合、Characterへの限定feedbackに `restore_state_fidelity` を追加する。

修復時は:

- explicit intensityを同じpredicateの適切な強度意味へ戻す
- unknownを肯定/否定へ変換しない
- supporting propositionを採用した場合はそのstateを保持する

固定文言やValidator出力の引用をユーザー向けspeechへ流さない。

## Unit Gate

#227 Unitでは最低限次を確認する。

1. primary intensity stateに `must_preserve_intensity_if_realized` が出る
2. unknownに `polarity_commitment=forbidden` が出る
3. supporting propositionに `optional_but_facet_complete_if_realized` とrequired facetsが出る
4. Promptが「supportingは省略可、採用時はfacet完全保持」を明示する
5. yes/no型unknownで肯定・否定markerによるpolarity確定を禁止する
6. `state_preserved` regeneration feedbackから `restore_state_fidelity` を生成する
7. raw Emotion/Drive/evidence path等の既存境界は維持する

## 非目標

- 特定の日本語程度副詞をstateへ固定対応させること
- Characterらしさ・かわいさ・自然さの採点
- Validator #229のfalse accept修正
- SpeechPerformancePlan / TTS / Bodyの実装

#227 Unit PASS後に#226↔#227 Adjacentを再実行し、その後にのみ#229へ進む。
