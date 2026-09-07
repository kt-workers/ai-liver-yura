# #337 D10 Body Expression Policy 実装対応

Owner: #337
Canonical:
- `body_expression_contracts.md`
- `body_expression_projection_policy.md`
Status: Implementation mapping

## 1. 目的

D10で追加されたCharacter Body Styleの数値投影契約を、既存#337の連続軸投影へ補完する。

既存のInternal State / Attention / Character Style Authorityは変更しない。Character文字列から新しい意味・Pose・Gestureを推測せず、exact confirmed valueとversioned policyだけを利用する。

## 2. D10 schema amendment

`CharacterStyleInfluenceRule`へ次を追加する。

- `dynamic_gain_overrides[]`
- `disposition`
  - `APPLY`
  - `NO_BASELINE_ONLY_DYNAMIC`
  - `IGNORE_EXPLICITLY`

`BodyExpressionDynamicGainOverride.gain`はfinite `[0, 2]`。同一rule内のaxis重複を禁止する。

同一`facet_id + confirmed_value`はpolicy内でexactly one ruleとし、substring・embedding・LLMによる近似matchingを追加しない。

## 3. Composition order

合成順を次で固定する。

```text
zero
→ Character static baseline
→ Internal State dynamic contribution
→ matching Character dynamic gainをdynamic contributionだけへ適用
→ static + modulated dynamic
→ final [-1,1] clamp
→ categorical Focus constraintを添付
```

Character baseline自身をgainで増幅しない。

複数のmatching ruleが同一axisへgainを持つ場合は`rule_id` Unicode code-point昇順で乗算する。積がfinite `[0,2]`外ならruntime clampで隠さず`INVALID_POLICY`としてfail-closedする。

## 4. Disposition boundary

- `APPLY`: static `axis_weights`を持つ。必要ならdynamic gainも持てる。
- `NO_BASELINE_ONLY_DYNAMIC`: static baselineを持たず、dynamic gainだけを持つ。
- `IGNORE_EXPLICITLY`: contribution/gainを持たないが、confirmed styleを意図的に無視するexact mappingとして扱う。

`IGNORE_EXPLICITLY`をunmapped扱いにせず、逆に未登録confirmed valueをsilent ignoreしない。

## 5. 後続境界

本補修では次を行わない。

- Character Definition本文の配置変更
- Character本文の意味変更
- fixed Pose / Motion preset追加
- Body Solver / Realtime Layerの数値制御
- renderer parameter mapping

`body_expression_projection_policy.md`に記載済みのYura calibration値はpolicy data Authorityとして維持し、Character Definitionの格納場所整理はそのowner工程で扱う。

## 6. Verification

Unitで次を固定する。

- APPLY baselineは維持され、gainはdynamic stateだけへ作用する
- dynamic-only ruleがbaselineを生成しない
- explicit ignoreがexact mappingとして成立する
- `facet_id + confirmed_value`重複をreject
- dispositionとpayloadの不整合をreject
- gain `[0,2]` validation
- multi-rule gain productのclosed-domain違反をfail-closed
- 既存Character style fixed baseline契約の互換維持

## 7. 工程

```text
#336 D10 Body Model補修（完了）
→ #337 D10 Body Expression policy補修
→ #338 D10 Motion Planning physical binding補修
→ #339 Solver / Continuous Controller残責務
```

#337を通常mergeしてから#338へ進む。
