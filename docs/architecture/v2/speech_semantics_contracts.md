# Speech Semantics Authority 型付き契約

## 1. 目的

この文書はIssue #362の実装正本である。Executiveが確定したSpeech intentから「何を伝えるか」を`SpeechSemanticPlan`として確定し、#330 Character Languageへ渡す。最終台詞、語尾、口調、TTS値、Body動作は生成しない。

責務分離はLLM呼出回数を増やすためのものではない。simple pathは信頼済みtyped directiveから決定論的に構成し、complex pathだけがFoundation LLM Roleを使う。両経路は同じcommit gateを通る。

## 2. Authority境界

- #328 ExecutiveはSpeech intent、semantic goal、target、constraint参照を確定する。
- #362 `SpeechSemanticAuthority`はproposition、required / optional / forbidden、polarity、certainty、degree、self-disclosure、question / new-direction budget、execution truth制約を確定する。
- #330 Character Languageは確定Planの意味を変更せず自然言語へ実現する。
- #363 VerifierはPlanとUtteranceの意味関係を観測するだけでPlanを書き換えない。
- #329 Execution AuthorityだけがActual Execution Factを所有する。発話計画は実行完了を主張しない。

Character Profile、raw Emotion / Desire / Drive、raw Execution payload、自然言語辞書、regexはWhat-to-say Authorityにならない。

## 3. 入力snapshot

`SpeechSemanticContextSnapshot`は次をimmutableに保持する。

- committed Executive decision IDとSpeech `ExecutiveIntent`
- source Event IDsとFoundation `RevisionVector`
- bounded `SpeechSemanticFact`
- authoritative `SpeechTruthConstraint`
- intentが参照できるconstraint IDs
- optional `DeterministicSpeechDirective`
- captured timestamp

Speech intentの`semantic_goal_ref`、`target_ref`、`constraint_refs`はsnapshot内のfact / constraintへgroundする。snapshot外参照、別decisionのintent、Speech以外のintentを拒否する。

`SpeechSemanticFact`はfact ID、subject、predicate、strict JSON value、evidence refsを持つ。Factは発話候補ではなくbounded truth/contextであり、Planのpropositionは使用したfact IDsを明示する。

## 4. Plan契約

`SpeechProposition`は次を持つ。

- proposition ID
- subject ref / predicate / strict JSON object
- `REQUIRED / OPTIONAL / FORBIDDEN`
- `AFFIRM / NEGATE / UNKNOWN`
- `CERTAIN / LIKELY / UNCERTAIN / UNKNOWN`
- optional finite degree `[0, 1]`
- bounded evidence fact refs

`SpeechSemanticPlan`はpropositionのほか、self-disclosure policy、question budget、new-direction budget、truth constraint refs、relationship / discourse constraint refsを持つ。

required / optional / forbiddenはproposition IDの別配列へ重複管理せず、各propositionのtyped dispositionを正本にする。Planは最終台詞、固定phrase、SSML、TTS parameter、Body joint、Execution completion factを持たない。

public callerはcommitted Planをstatus値だけで直接製造できない。LLM / deterministic builderは`SpeechSemanticCandidate`までを作り、Authorityのvalidated commitだけがimmutable Planを構築する。

## 5. Commit gate

Authorityは次をfail-closedで検証する。

1. candidate identity、decision / intent / source Event identity。
2. source / goal / attention revisionのsnapshot・candidate・current三者一致。
3. requestにfreezeしたsnapshotとcommit対象snapshotの一致。
4. proposition evidence refsがbounded fact IDsの部分集合。
5. intentのsemantic goal / target / constraint refsがsnapshotへground済み。
6. candidate truth constraint refsがExecutive / upstreamのauthoritative集合と完全一致。
7. execution truth制約の対象factとproposition polarity / certainty / valueのclosed整合。
8. question / new-direction budgetがauthoritative上限以下。
9. forbidden propositionをrequired / optionalとして扱わないtyped schema。
10. 同じplan ID・同じintentの二重commit拒否。

LLM candidate自身がtruth constraintやbudgetを空にして安全条件を省略することはできない。Authorityはsnapshotのauthoritative要件を正本にする。

## 6. Simple path

`DeterministicSpeechDirective`がsnapshotにある場合、専用LLMを呼ばずcandidateを構成できる。directiveはtyped propositionとpolicyをすでに持ち、semantic goal / evidence / truth constraintへgroundされる。

simple判定をkeyword / regex / fixed phraseで行わない。typed directiveの存在とpolicyだけで決める。directiveがない、またはcomplex policyがLLMを要求する場合はcomplex pathを使う。

## 7. Complex LLM path

Role IDは`speech_semantics`、schemaはversioned request / candidate schemaとする。requestはsnapshot全体をfreezeし、Provider SDK objectやunbounded text historyを含めない。

LLM outputはstrict field setの`SpeechSemanticCandidate`であり、Authorityを持たない。transport identity、schema、timing、revisionをFoundation `validate_role_exchange()`で検証し、await後にlive ownerからcurrent `RevisionVector`を再取得してcommitする。呼出時revisionをcurrentとして再利用しない。

slow Speech Semantics中もcurrent Speech、Body、Input、unrelated Activityをblockしない。Domain Authority lockにawait、Provider callback、外部I/Oを含めない。

## 8. Failureと後続境界

schema不正、stale、unbounded ref、truth矛盾、budget超過はPlanをcommitしない。free-form Provider例外やpayloadをPlanへコピーしない。

#330は`SpeechSemanticPlan`だけを入力Authorityとして使い、raw Executive contextやraw internal stateを再解釈しない。#363はPlanのproposition IDとCharacter realization refsを比較できる。

## 9. 検証

- direct answer / self-disclosure / unknown
- positive / negative / certainty / degree
- required / optional / forbidden
- question / new-direction budget
- execution truth一致・完了捏造拒否
- snapshot外fact / constraint / target拒否
- deterministic simple pathでLLM未呼出
- complex LLM typed exchange / schema / identity / timing
- source / goal / attentionの各stale reject
- slow complex Role中にunrelated simple pathが完了
- same intent / plan競合commitは高々1件成功
- final utterance / Character style / TTS / Body / Execution Authority非混入
