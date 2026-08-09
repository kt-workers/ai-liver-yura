# Internal State Target-specific Evidence v1.0.1

## 背景

Character / Response Validator Lab（#223）で `target=internal_state/joy`、`joy=0.0`、`amusement=0.0`、`curiosity=0.82`、`engagement=0.78` を与えたところ、Characterは「うん、少し楽しいよ。」と生成し、Response Validatorも `accepted=true` とした。

このケースではMemory、recent speech、conversation summary、Body/TTS/Avatar/RuntimeCoordinatorを使用していないため、問題はCharacter / Validatorの意味整合性境界に局在する。

既存PR #219はtyped targetとcurrent structured state全体を同時に提示し、「別状態をtargetへ代用しない」と指示していた。しかしLLMへ状態全体の意味解釈を委ねるだけでは、targetに直接対応する事実と補助状態の優先順位が十分に固定されなかった。

## 目的

内部状態への直接質問では、Coreがtyped targetに直結するstructured evidenceを先に投影し、CharacterとResponse Validatorが同じtarget-specific evidenceを共有する。

固定回答、固定言い換え辞書、raw text regex、通常語禁止リストは追加しない。

## 契約

```text
StructuredInputMeaning.target
+ current Emotion / Drive / Situation
+ current ResponseContentPlanの必要最小限のDesire evidence
        ↓
Target-specific Evidence Projection
        ↓
Character
        ↓
Response Validator
```

### exact dimension

`target=joy`のようにstate schema内で同名dimensionを特定できる場合、pathと値を直接evidenceとして投影する。

```json
{
  "target": {"type": "internal_state", "id": "joy"},
  "scope": "exact_dimension",
  "evidence_available": true,
  "target_evidence": [
    {
      "path": "emotion.current.reactive.joy",
      "key": "joy",
      "value": 0.0
    }
  ]
}
```

Characterはtargetの存在・強さについてこのevidenceを優先する。curiosity、engagement、energy等のnon-target stateは話し方や関心の向きには使えるが、joyの存在を肯定する根拠にはしない。

### aggregate target

`current_feeling/current_mood`のように単一dimensionではなくEmotion全体を問うtargetは `emotion_overview` として扱う。

一つの感情だけへ縮約せず、現在のEmotion構造全体を回答根拠とする。

### desire target

`current_desire`では、利用可能な場合はcurrent ResponseContentPlanの `primary_desire` をtarget evidenceとして使用する。

Memory本文や過去発話を現在Desireの正本にはしない。将来ResponseContextへtyped DesireStateが直接追加された場合は、そのtyped stateをprimary sourceへ昇格する。

### evidence unavailable

直接evidenceが存在しない場合は `evidence_available=false` とする。

別の内部状態からtargetを推測して断定しない。Characterは不足したevidenceの範囲を越えず自然に直接回答し、Validatorもnon-target stateを根拠にした断定を受理しない。

## Validator

Response Validatorはまず発話がtyped targetについて何を主張しているかを意味的に評価し、その主張をtarget-specific evidenceと比較する。

特にexact numeric evidenceが0.0であるtargetを、発話が現在存在する・少し存在する・高い等と肯定した場合は `accepted=false` とする。

これは日本語文字列照合ではなく、typed targetとstructured evidenceの意味整合性検証である。

## 非目標

- `joy=0 -> 「楽しくない」` の固定回答化
- targetごとの日本語テンプレート
- raw user textの再解析
- curiosity/engagement等を削除すること
- Memory ranking / retrieval変更
- #221 Body lifecycle問題の修正

## 検証

#223 Character / Response Validator Labで次を確認する。

1. `joy=0.0` / `amusement=0.0` / high curiosityで「少し楽しい」を肯定しない。
2. `anger=0.0`で別stateを理由に怒りを肯定しない。
3. `current_feeling`ではEmotion overviewから自然に回答する。
4. `current_desire`ではDesire evidenceを優先し、generic moodへ逃げない。
5. target-specific truthと矛盾するcandidateをValidatorがrejectし、再生成へ進める。
6. 内部key/path/valueを発話へ露出しない。
7. question/new-direction budget、既存反復検出、存在境界を維持する。
