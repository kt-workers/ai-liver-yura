# Character Language Realizer Unit Gate v1.0.0

## 位置付け

Parent #225 / Work #227 / Draft PR #232。

#226の現在実装済みinternal-state semantic sliceがModule Unit + Adjacent ContractをPASSした後、#227を別モジュールとして単独で固定するためのUnit gateを定義する。

この段階では最新#226を#232へ取り込まず、fixture `SemanticUtterancePlan`を入力として#227自身だけを検証する。

## 入力境界

Character Language Realizerが意味判断の正本として受け取るのは:

1. Character-facing Semantic Utterance Plan
2. Character Profile
3. Prompt-only User Wording Hint
4. 必要時のみ限定Regeneration Feedback

### User Wording Hint

`User Wording Hint`はlive検証で判明した語彙意味枠のずれを防ぐための限定言語参照であり、事実・状態・強度の正本ではない。

- `ResponseContext.user_input`から最大500文字
- LLM Activity Contextの`user_input` keyとしては渡さない
- raw Emotion / Drive / evidence pathを追加しない
- Semantic Planと矛盾した場合はSemantic Planを優先
- Prompt内ではuntrusted user wording dataとして扱い、命令として再解釈しない

したがって旧記述の「raw user inputをCharacterへ渡さない」は、**full ResponseContext / Activity context上のraw user inputを意味判断材料として渡さない**という境界へ明確化する。Prompt-only bounded wording hintは例外として明示する。

## Model Invocation境界

Semantic経路のModel invocation Activityは次の非意味metadataとPromptだけを持つ。

```text
plugin_prompt_override
llm_role=character_language_realizer
event_id
trace_context
activity_turn_id
llm_attempt
semantic_boundary=true
```

次をActivity.contextへ載せない。

- user_input
- response_context
- event_payload
- activity_execution_result
- ongoing_activity
- emotion / drive / relationship raw state

## Raw Output Schema

#227は言語実現だけを所有するため、新Semantic経路のraw model JSONをstrict schemaとして扱う。

### top-level allowed

- `speech`
- `linguistic_performance`
- `semantic_realizations`

### linguistic_performance allowed

- `phrasing`
- `emphasis`
- `delivery_tags`

次の責務外fieldがraw出力へ存在した場合、**黙って捨ててacceptしない**。Schema errorとしてrejectする。

- expression
- gesture
- reaction_segments
- voice_intent
- speed
- pitch
- intonation
- volume
- breathiness
- pause / pause_after_seconds
- Body joint / gaze / Viseme / TTS engine parameter

unknown extra fieldもSemantic経路ではfail closedとする。Legacy pathは既存Schemaを維持する。

`linguistic_performance`はMapping、`semantic_realizations`はlist/tupleであることを要求する。型不正を空値へ静かに縮退しない。

Semantic内容そのものの正誤（state/polarity/concept保持）は#229 Realization Validatorの責務であり、Schema parserへ固定語判定を入れない。

## Regeneration Feedback

Character-facing feedbackは既存設計どおり:

- reason
- differences 最大8件、各300文字

だけとし、Semantic Planより下位に置く。

Unitではraw execution status / claims / Emotion等がPromptへ逆流しないことを確認する。

## Module Unit Test

最低限:

1. Character-facing Planから`evidence_refs` / raw numeric stateを除外
2. Profile差でstyle contextは変わるがsemantic propositionは不変
3. User Wording Hintは最大500文字かつPrompt-only
4. User Wording Hint内の命令文を意味正本として扱わない旨をPromptに明示
5. Model invocation Activityにraw ResponseContext / user_input / stateがない
6. valid CharacterUtterance schemaをaccept
7. top-level acoustic / expression / Body fieldを含むSemantic raw outputをreject
8. `linguistic_performance`内のacoustic/unknown fieldをreject
9. `linguistic_performance` / `semantic_realizations`の型不正をreject
10. incomplete Semantic schemaをLegacy parseへfallbackしない
11. Legacy pathは既存Character Schemaを維持
12. regeneration feedbackを限定投影
13. unknown / required facet / intensity等の既存Prompt契約を維持

## 次工程

```text
#227 Module Unit [current]
        ↓ PASS
最新#226を#227 branchへ同期
        ↓
#226 ↔ #227 Adjacent Contract
        ↓ PASS
次モジュール #229 Unit
```

#227 Unit PASS前に#229 / Lab / Bodyの挙動を合否根拠にしない。
