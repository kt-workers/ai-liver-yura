# SemanticUtterance Exact Dimension Resolution v1.0.0

## 位置付け

Parent #225 / Work #226 / Draft PR #231。

#226のAdjacent Contract監査中に、direct internal-state targetの同名dimension解決がMapping走査順へ依存し得ることを確認したため、Module Unit gateへ戻って意味解決規則を固定する。

## 背景

既存#210設計 `internal_state_target_specific_evidence_v1.0.1.md` は `target=joy` のexact evidence例を次としている。

```text
emotion.current.reactive.joy
```

現行Emotion domainでも `joy / amusement / anger / sadness / fear / surprise / discomfort / emotional_pressure` は `ReactiveEmotionState` が所有する短期感情dimensionである。

一方、現行`ResponseSemanticsPlanner._find_dimension()`はnested Mappingをdepth-firstで走査し、最初に同名keyを発見した時点で返す。そのため、互換payload・異常payload・将来schemaで同名dimensionが複数存在すると、dictionary insertion orderが意味決定へ影響し得る。

## 原則

発言意味はMappingの格納順で決めない。

```text
Typed target
+ known domain ownership / canonical path
        ↓
deterministic exact-dimension resolution
        ↓
SemanticProposition
```

### Reactive Emotion target

以下はReactive Emotion dimensionとして扱う。

- joy
- amusement
- anger
- sadness
- fear
- surprise
- discomfort
- emotional_pressure

これらをEmotionから解決する際は、同名候補のうち`reactive`配下を最優先する。

優先順位:

1. `emotion.current.reactive.<target>`
2. `emotion.reactive.<target>`
3. compatibilityとしてその他のEmotion内exact `<target>`

`*_joy`のようなsuffix一致は既存Compatibilityとして残してよいが、canonical exact keyより優先しない。

### その他のtarget

Drive / Situationや、Emotionの非Reactive dimensionについても、候補を収集してから決定的な順位で選ぶ。

同一source内の候補順位は最低限:

1. exact key match
2. compatibility suffix match
3. path depthが浅いもの
4. 最後のtie-breakはpath文字列順

これによりMapping insertion orderを意味へ反映しない。

source間の既存優先順位は維持する。

```text
Emotion
> Drive
> Situation
> current Desire fallback
```

## 競合値

canonical reactive pathが存在する場合、他の同名compatibility値と内容が異なってもcanonical reactive valueを採用する。

canonical pathが存在しないCompatibility入力で複数候補がある場合も、上記の決定的順位で1件を選択し、dictionary順へ依存させない。

これは任意の別状態からtargetを推測する規則ではない。同じtyped target idへ一致した候補だけが対象である。

## 非目標

- Emotion domain schemaの再設計
- baseline / mood等の新規概念追加
- #210 Compatibility Promptの変更
- #227 Character Language Realizer
- #229 Validator
- #193 Discourse Appraisal
- raw user textからtargetを再推定すること

## Unit Test

最低限次を確認する。

1. `baseline.joy`が先に格納されても`current.reactive.joy`を選ぶ
2. Mappingの挿入順を逆転しても同じSemanticPropositionになる
3. `emotion.reactive.joy`はcanonical compatibility pathとして任意nested exact matchより優先される
4. reactive pathが無い場合はexact key > suffix key
5. exact候補が同順位の場合もpath文字列順等で決定的になり、挿入順に依存しない
6. evidence_refsは実際に採用した1 pathだけを保持する
7. raw numeric valueはPlan serializationへ露出しない

Unit再PASS後、#226 Adjacent Contract CIを再実行する。
