# 自然言語 Lexical Semantic Matcher 横断監査 — 2026-08-11

## 目的

Issue #288。

open-ended自然言語を有限語彙、正規表現、語尾、substring、表面n-gramで意味判定している実装を、`develop` と未統合 #229 stack から洗い出す。

本監査の判定基準は `docs/design/natural_language_lexical_decision_policy_v1.0.0.md`。

## 重大度

**Architecture Regression / Large impact**。

問題は `_EXPLICIT_INTENSITY_MARKERS` 一箇所ではない。少なくとも入力意味、Activity intent、確認回答、Character発話のClaim、質問/話題予算、存在境界、Realization intensityに同型パターンが存在する。

共通原因は次の誤った例外規則である。

> LLMの補助・Safety Net・Fallback・Guardであれば、少数の自然語matcherをdeterministicに使ってよい。

この例外規則を撤回する。

---

## 判定区分

- **REMOVE / REDESIGN**: open-ended自然言語のsemantic authorityになっている。撤去しtyped semantic境界へ移す。
- **REMOVE LEGACY**: 現主経路ではないが同型負債。残置せず削除する。
- **KEEP**: closed protocol / security / domain lexical dataなど、本Policyの許容対象。
- **REVIEW**: 表面特徴をsemantic qualityへ使っており、辞書ではないがparaphrase耐性の観点で同じ危険を持つ。

---

## 監査結果

| 区分 | ファイル / 対象 | 現在の役割 | 問題 | 置換方針 | 主影響 |
|---|---|---|---|---|---|
| REMOVE / REDESIGN | 未統合 `app/runtime/character_realization_validator.py::_EXPLICIT_INTENSITY_MARKERS` | speech/evidence spanにdegree語があるかをRuntimeで判定 | 未列挙言い換えがすり抜ける。語彙追加が無限化。Runtimeが自然語意味を再解釈 | 独立Realization Semantic Interpreterがspeechからtyped realized semanticsを抽出。RuntimeはPlanとのtyped比較とevidence span実在確認のみ | #229, #223, PR #233/#234, intensity/state fidelity tests, Live verification |
| REMOVE / REDESIGN | `app/runtime/response_budget_validator.py::ResponseSpeechActAnalyzer` | 質問数・新話題数を日本語語尾/phrase regexで数える | 質問/transitionの言い換えを取りこぼす/誤検出 | speech-act/discourse semantic interpreter → typed counts/relations → budget deterministic compare | question/new-direction budget, closing behavior, #200系回帰 |
| REMOVE / REDESIGN | `app/runtime/response_claim_validator.py::IndependentClaimExtractor` | speechからActivity success/failure/completion/capability等Claimをregex抽出 | 実行安全保証が有限表現に依存。未知言い換えがclaim検出を回避 | independent Claim Semantic Interpreter → typed `Claim` →既存`DeterministicFactValidator` | Activity truthfulness, #177/#184系, plugins, Character Validator |
| REMOVE / REDESIGN | `response_claim_validator.py::_EMBODIED_ACTION_COMPLETION_PATTERN` | Body actionを実行済みと述べたか検出 | 身体動作の言い換えを有限リストで判定 | typed speech Claim / Expression execution claimとして抽出しBody/Activity execution factと比較 | Body指示、#214/#211系、存在表現 |
| REMOVE / REDESIGN | `response_claim_validator.py::_UNSUPPORTED_EXPERIENCE_PATTERN`, `_PHYSICAL_BODY_CLAIM_PATTERN` | 未根拠実体験/物理身体claimをspeech regexで検出 | existence boundary保証が有限語彙に依存 | typed unsupported-experience / embodied-existence claimをSemantic Validatorで検証 | Character existence boundary, #229, legacy ResponseValidator |
| REMOVE / REDESIGN | `response_claim_validator.py::_directive_conflicts` のquestion/new-direction抽出 | Directive budgetをspeech表面から再判定 | `response_budget_validator`と責務重複し、同じ有限語彙依存 | semantic speech analysis結果を1正本として共有。budget compareは一箇所 | Response validation全体、重複判定削除 |
| REVIEW → REDESIGN | `response_claim_validator.py::_autonomous_topic_conflicts` | topicとspeechの2文字bigram overlapでtopic drift判定 | 有限辞書ではないがparaphraseで正しい発話をreject、表面一致した別意味をaccept | Discourse/Semantic realizationでtyped topic relationを検証 | autonomous talk, topic continuity, #193連携 |
| REMOVE / REDESIGN | `app/runtime/pending_confirmation.py::ConfirmationResolver` | affirmative/negative/cancel/clarification/new requestをregex判定 | 実行可否に関わる意味判定が有限語彙依存 | confirmation-aware semantic interpreter → `ConfirmationResolution`; invalid/low-confidenceは実行せず再確認 | **高安全影響**: Activity start/stop/switch/constraints confirmation |
| REMOVE / REDESIGN | `app/core/plugins/user_request.py::interpret_user_request` | LLM失敗時のexecution/knowledge/past/negative fallback | “high confidence fallback”でも未知言い換えを扱えない。Input Meaningと二重解釈 | `StructuredInputMeaning`を正本化。semantic failure時はambiguous/clarification、語彙fallbackなし | BehaviorPlanningContextBuilder, SituationEvaluator, BehaviorPlanner |
| REMOVE / REDESIGN | `app/runtime/situation_evaluator.py` の `_is_negated_expression`, `_non_execution`, `_is_greeting`, `_is_administrative_direction`, `_is_hypothetical`, `_speech_act` | LLM前/失敗時にraw user textを決定論的semantic分類 | Input Meaning LLM分離設計と直接矛盾。中心経路をshort-circuit | `InputMeaningInterpreter → StructuredInputMeaning`をproduction正本として統合。Runtimeはtyped fieldsをprojection | **最大影響**: 全USER_TEXT routing, Activity planning, speech act, greeting/negation/hypothetical/past/knowledge |
| REMOVE LEGACY | `app/runtime/activity_matcher_resolver.py::LegacyActivityMatcherAdapter` | `start_markers/stop_markers` exact matchでActivity intent決定 | Activity intentの有限語彙分類 | typed activity intent / semantic candidate resultのみ利用 | Activity matcher compatibility tests / definitions |
| REMOVE LEGACY | `app/shared/contracts/activity.py::ActivityDefinition.start_markers/stop_markers` | Legacy matcher用natural language marker contract | Plugin/Activity定義に有限自然語辞書を恒久APIとして残す | contractから段階削除。semantic descriptionsはLLM candidate context用に限定 | ActivityDefinition constructors/tests/docs/plugins |
| REMOVE LEGACY | `app/domain/conversation_utterance_policy.py::_ACKNOWLEDGEMENT_CLAUSES`, `is_low_information_acknowledgement` | acknowledgementを有限句で互換判定 | 主経路はtyped speech_actへ移行済みだが負債を残す | callsite不存在を確認後削除 | compatibility testsのみ想定 |
| KEEP | `app/domain/activity_constraints.py::_schema_keywords` | JSON-like constraint schemaのclosed keyword set | open natural languageではない | 維持。protocol exception | なし |
| KEEP | `app/utils/trace.py` secret/redaction/technical severity regex | secret key, token, internal trace codeの検出 | semantic user-language判定ではない | 維持。security/technical exception | なし |
| KEEP | `app/domain/body_instruction.py` | typed body semantic contract | raw text matcherなし | 維持 | なし |
| KEEP | `app/runtime/ongoing_input.py::OngoingInputInterpreter` | typed `SituationAnalysis`からongoing relationを決定 | raw text再解釈なし | 維持。入力analysis正本化後のconsumerとして利用 | upstream replacementのみ |
| KEEP | `app/runtime/interaction_reaction_policy.py` | closed internal reason codeとcooldown | natural languageではない | 維持 | なし |
| KEEP | TTS pronunciation dictionary | 発音置換というdomain lexical data | semantic intent/state判定ではない | 維持。一般semantic判定へ流用禁止 | TTSのみ |

---

## 追加で確認した構造的問題

### 1. Input Meaning分離がproductionの唯一の入口になっていない

`StructuredInputMeaning` / `InputMeaningInterpreter` / `SeparatedSituationEvaluationAdapter` は既に存在する。

しかし通常Runtimeでは `SituationEvaluator` が直接使われ、その内部でraw user textのdeterministic lexical classificationを先に行っている。

したがって #288 は単なるmatcher削除ではなく、**既に作ったInput Meaning境界をproduction semantic authorityへ昇格する統合作業**を含む。

### 2. Character speechのself-reportと独立検証の境界が未完成

`CharacterResponse`にはtyped `claim_details` がある一方、独立Claimは`IndependentClaimExtractor`のregexで生成している。

正規形は:

```text
Character speech
→ independent Claim Semantic Interpreter
→ typed Claim
→ DeterministicFactValidator
→ ActivityExecutionResult / Capability factとの比較
```

Characterの自己申告`claim_details`だけを信頼せず、独立interpretationを維持する。

### 3. Budget検証が二重化

質問/new-directionは:

- `ResponseBudgetValidator`
- `DeterministicFactValidator._directive_conflicts`

の両方でspeech表面解析されている。

semantic speech analysisを一正本へ統合し、budget比較の重複をなくす。

### 4. #229 evidence spanの責務

Evidence span自体は削除不要。

Runtimeで許可するのは:

- non-empty
- speech中に実在
- typed semantic resultとの参照関係schema

まで。

spanの中に `少し/かなり/...` 等があるかをRuntimeが判断してはならない。

---

## 影響範囲

### P0 — 実行安全性

1. Confirmation resolution
   - affirmative誤判定はActivity実行へ直結
   - 修正後もfail closed必須
2. Execution/capability claim truthfulness
   - Characterが実行していない操作を実行済みと述べない保証
   - regex削除前にtyped Claim interpreterを用意する
3. Activity intent / stop / switch
   - user request解釈の変更が実行routingへ波及

### P1 — 会話意味

4. Input speech act / negation / hypothetical / past / knowledge
5. Response question/new-direction budget
6. existence boundary
7. #229 internal-state state/intensity fidelity

### P2 — 会話品質

8. autonomous topic continuity
9. acknowledgement compatibility helper

---

## 影響する主要テスト群

最低限、以下を再設計・再実行する。

- `tests/test_user_request.py`
- `tests/test_situation_evaluator.py` およびSituation/Behavior Planner関連
- `tests/test_behavior_planner.py`
- `tests/test_activity_matcher_resolver.py`
- Pending Confirmation / Confirmation Coordinator関連
- `tests/test_response_claim_validator.py`
- `tests/test_response_budget_validator.py`
- Character Response Pipeline / existence boundary / Activity truthfulness tests
- #229 `test_character_realization_*`
- #223 Lab focused tests
- `tests/test_architecture_boundaries.py`

また「既知語の正常系」だけでなく、同じ意味の未観測paraphraseを複数含むAdjacent/LLM verificationを追加する。

---

## 修正フェーズ

### Phase 1: Architecture gate

- 本Policy / 本Auditを正本化
- Architecture static testを追加
- 新たなfinite semantic matcherの追加を禁止

### Phase 2: Input semantic authority

- `interpret_user_request`依存撤去
- `SituationEvaluator` raw lexical shortcuts撤去
- `SeparatedSituationEvaluationAdapter` / `InputMeaningInterpreter`をproduction正本へ接続
- semantic failureはclarification/fail closed

### Phase 3: Activity / Confirmation

- Legacy `start_markers/stop_markers`撤去
- ConfirmationResolverをtyped semantic interpretationへ置換
- start/stop/switch/constraint confirmationを回帰

### Phase 4: Character output semantic validation

- independent Claim Semantic Interpreter導入
- question/discourse semantic analysis導入
- DeterministicFactValidator / budget comparatorはtyped結果だけを見る
- existence boundary/topic relationもtyped semanticsへ移行

### Phase 5: #229 Realization

- `_EXPLICIT_INTENSITY_MARKERS`撤去
- evidence span lexical check撤去
- blind/independent realized-semantics extractionを導入
- `それなりに` → `そこそこ` のtest変更を撤回
- unseen paraphraseを含める

### Phase 6: Verification

```text
Unit
→ Adjacent
→ affected regression
→ #223 Lab 12 cases + paraphrase variation
→ System Verification
```

3回目Liveおよび#227/#229 freezeはPhase 5まで完了後に再開する。

---

## 再発防止判定

今後、自然言語semantic decisionに新しいliteral/regexを追加する変更は、レビュー時に次を証明しなければならない。

- closed protocol / security / domain lexical dataである
- open-ended paraphraseをsemantic authorityとして分類していない
- typed semantic boundaryを迂回していない

証明できない場合はmerge不可。
