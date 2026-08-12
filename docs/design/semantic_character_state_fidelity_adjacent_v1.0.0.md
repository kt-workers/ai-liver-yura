# Semantic Plan → Character State Fidelity Adjacent v1.0.0

## 位置付け

Parent #225 / Work #226 + #227 / Draft PR #231 + #232。

Extended Verificationで検出したstate fidelity回帰に対して、#227 Module Unitを再freezeした後に実施する、#226 → #227間だけの追加Adjacent Contractを定義する。

既存 `semantic_to_character_language_realizer_adjacent_contract_v1.0.0.md` を置き換えず、explicit intensity / unknown polarity / supporting proposition fidelityだけを追加確認する。

この段階では#229 Validator、#223 Lab、実LLM、TTS、Bodyを接続しない。

## 対象経路

```text
Activity / Event payload
        ↓
InternalStateAwareResponseContextBuilder
        ↓
ResponseSemanticsPlanner (#226)
        ↓
SemanticUtterancePlan
        ↓
CharacterLanguageRealizerPromptBuilder (#227)
        ↓
Character-facing Plan / Facet Contract
```

SemanticUtterancePlanをテスト内で手作りせず、production Plannerが実際に生成したPlanを#227へ渡す。

## Contract A: explicit intensity

入力例:

```text
target = joy
emotion.current.reactive.joy = 0.78
```

#226が `joy=high / certainty=high` を生成した場合、#227 Character-facing contractは:

- state = high
- state_semantics = explicit_intensity_state
- state_fidelity = preserve_exact_semantic_state（primary contract）
- intensity_fidelity = must_preserve_intensity_if_realized

を保持する。

raw `0.78`、evidence path、Emotion payloadはCharacter Promptへ流さない。

## Contract B: unknown without polarity

入力例:

```text
target = sadness
emotion.current.reactive に sadness が存在しない
```

#226が `sadness=unknown / certainty=low` を生成した場合、#227は:

- state = unknown
- certainty = low
- state_semantics = unknown_without_polarity_guess
- polarity_commitment = forbidden

を保持する。

User Wording Hintがyes/no型の「悲しい？」でも、Character-facing stateをpresent/absentへ補完しない。

## Contract C: mixed current_feeling supporting propositions

入力例:

```text
joy = 0.78
anger = 0.48
calm = 0.22
amusement = 0.02
```

#226がprimary `current_feeling=overview` と supporting dimensions を生成した場合、#227は各supporting propositionを:

- `realization_policy=optional_but_facet_complete_if_realized`
- `if_realized_required_facets=[predicate,state,certainty]`（concept non-null時はconceptも）
- intensity stateなら `intensity_fidelity=must_preserve_intensity_if_realized`

として投影する。

supporting propositionは省略可能であり、全てを必ず発話する要求ではない。しかしCharacterが採用する場合は、#226が確定したstate/certaintyを落とさない契約を渡す。

## Security / Responsibility Boundary

全ケースで以下を維持する。

- `evidence_refs`をPromptへ出さない
- `emotion.current.reactive.*` pathをPromptへ出さない
- raw numeric Emotion/DriveをPromptへ出さない
- Characterがstateを再計算しない
- 特定の日本語程度語辞書を導入しない

## Adjacent Test Gate

最低限:

1. production Planner: `joy=.78` → `joy=high/high`
2. #227 Prompt: explicit intensity fidelity contractを保持
3. production Planner: missing sadness → `unknown/low`
4. #227 Prompt: unknown + polarity forbiddenを保持
5. production Planner: mixed current_feeling → expected overview/supporting states
6. #227 Prompt: supporting propositionsをoptional-but-facet-completeとして投影
7. raw numeric/evidence pathがCharacter Promptへ出ない

## 非目標

- Character LLMが実際にどの日本語を出すか
- Validatorが誤発話をrejectできるか（#229）
- regeneration loop
- Lab / Render
- SpeechPerformancePlan / TTS / Body

## 合格後

このAdjacent gateがPASSしたら、#227 State Fidelity sliceを再freezeする。

その後にだけ#229へ進み、Extended Verificationで観測したfalse acceptに対するValidator防衛線を設計・Unit検証する。
