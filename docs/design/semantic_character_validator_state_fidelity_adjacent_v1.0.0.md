# Semantic → Character → Validator State Fidelity Adjacent v1.0.0

## 位置付け

Parent #225 / Work #226 + #227 + #229 / Draft PR #231 + #232 + #233。

Extended Verificationで検出したE1/E2/E3/E4型の意味崩れについて、#227 State Fidelity Unit + #226→#227 Adjacent、#229 State Fidelity Unitをそれぞれ再freezeした後に実施する3モジュールAdjacent Contract。

この段階ではSemantic Lab / 実LLM / TTS / Body / Avatar / full Runtimeを接続しない。

## 対象経路

```text
production input context
    ↓
#226 ResponseSemanticsPlanner
    ↓
SemanticUtterancePlan
    ↓
#227 CharacterLanguageRealizerService / Prompt
    ↓
CharacterResponse compatibility
    ↓
#229 CharacterRealizationValidator
```

#226のPlanをテスト内で手作りして合否を作らない。production Plannerが確定したPlanを#227/#229へ渡す。

Character/Validator LLMはfake modelを用いる。自然文の固定語辞書をテストするのではなく、Validator fakeが返すsemantic diagnosisに対して#229 Runtimeが正しくfail closedするかを確認する。

## Contract A: explicit intensity weakened

production input:

```text
target=joy
joy=.78
```

期待Plan:

```text
joy=high / certainty=high
```

Character候補がprimary realization IDを持っていても、Validatorが:

```text
state_fidelity=weakened
```

と診断した場合、top-level `accepted=true` でもRuntimeはrejectする。

逆にValidatorがsame candidateについて`exact`と診断した場合にだけRuntime structural gateを通過できる。自然文が本当にexactかどうかはfake model自身で検証しないため、本Adjacentでは「診断構造の伝播」を試験対象とする。

## Contract B: unknown committed

production input:

```text
target=sadness
sadness evidence missing または explicit null
```

期待Plan:

```text
sadness=unknown
```

Character候補がunknownを肯定/否定へ確定したとValidator fakeが:

```text
state_fidelity=unknown_committed
```

と返した場合、top-level accepted=trueでもrejectする。

polarityを確定しない候補に対し`exact`を返した場合はaccept可能。

## Contract C: mixed current_feeling supporting fidelity

production input:

```text
joy=.78
anger=.48
calm=.22
amusement=.02
```

期待Plan:

```text
current_feeling=overview
joy=high
anger=moderate
calm=low
amusement=absent
```

Characterがsupporting realization IDを列挙した場合、#229はその各IDのper-proposition checkを要求する。

primary aggregateがall trueでも、採用済みsupporting `joy` / `calm`等が`weakened`なら全体rejectする。

Characterがsupporting propositionを列挙しない場合、その省略自体はrejectしない。

## Contract D: exact candidate

Characterが列挙した全realization IDについてValidator fakeが:

- predicate_preserved=true
- state_preserved=true
- state_fidelity=exact
- certainty_preserved=true
- concept_preserved=true

を返し、aggregate semantic_checksも整合していればacceptする。

## Boundary Contract

Character / Validator invocation Activity Contextは引き続きraw state free:

- `user_input` keyなし
- full `response_context`なし
- raw Emotion / Driveなし
- `event_payload`なし
- `activity_execution_result`なし
- `semantic_boundary=true`

Prompt内のbounded User Wording Hintは既存例外として許可し、state/evidence正本にはしない。

## Adjacent Gate

最低限:

1. E1相当 production Planがhighを生成
2. high→weakened診断をRuntimeがreject
3. E2/E3相当 production Planがunknownを生成
4. unknown_committed診断をRuntimeがreject
5. unknown exact診断はaccept
6. E4相当mixed Planのsupporting statesをproduction Plannerが生成
7. supporting weakened診断をprimary aggregate=trueでもreject
8. adopted realizationすべてexactならaccept
9. Character/Validator model boundaryがraw state free
10. unplanned realization IDやmissing per-proposition checkの既存fail-closedを後退させない

## 非目標

- 特定日本語をhigh/moderate/lowへ固定対応させること
- Validator LLM自身の意味判定精度（実LLM Labで確認）
- Characterらしさ・文章品質
- SpeechPerformancePlan / TTS / Body / Avatar

## 合格後

この3-module AdjacentがPASSしたら#226→#227→#229 State Fidelity sliceを再freezeする。

その後にのみ#229 current HEADをSemantic Labへ同期し、Lab fake schema追従 + focused CIを実施する。focused CI PASS後、Extended 6ケースを実LLMで再実行する。
