# Natural Language Lexical Decision Policy v1.0.0

## 位置付け

Issue #288。

本方針は、ユーザー入力・Character発話・Memory本文・その他のopen-ended自然言語を、有限個の語・フレーズ・正規表現・substring条件へ照合して意味、意図、状態、事実主張、発話行為を決定する実装を禁止する。

この制約は「通常経路」「Fallback」「Guard」「Safety Net」「Compatibility」の名称に関係なく適用する。

## 背景

有限語彙による自然言語意味判定には構造的な欠陥がある。

1. 列挙されていない同義表現・言い換え・語順変化を必ず取りこぼす
2. 発見した表現を追加するほど辞書が肥大化し、なお未観測表現を覆えない
3. テスト文言やCharacter表現を実装辞書へ寄せる圧力が生じる
4. typed semantic contractとLLM意味解釈の責務がraw text matcherへ逆流する
5. 高確信度Fallbackと称しても、未列挙表現に対するrecall問題は解消しない

したがって、有限列挙を「完全ではないが保守的な補助」としてsemantic authorityへ使うことも禁止する。

## 禁止対象

### 1. 自然言語から意味を決める有限語彙

以下のいずれかでopen-ended自然言語を分類・判定してはならない。

- `MARKERS / KEYWORDS / WORDS / PHRASES / SYNONYMS / ALIASES` 等の語彙集合
- `text in (...)` / `marker in text`
- `startswith` / `endswith`
- 正規表現による自然語フレーズ分類
- 固定語からEmotion / Desire / Drive / state / intensityを推定
- 固定語からspeech act / question / acknowledgement / closingを推定
- 固定語からActivity intent / start / stop / continueを推定
- 固定語からclaim / execution status / capability / experienceを推定
- 固定語からconfirmation affirmative / negative / cancel / clarificationを推定
- 固定語からtopic transition / discourse relationを推定

### 2. 名称を変えた同型実装

次の名称でも例外にならない。

- deterministic guard
- semantic surface guard
- safety net
- high-confidence fallback
- compatibility matcher
- legacy matcher
- fast path
- heuristic

意味判定の正しさが有限自然語リストへ依存するなら禁止対象である。

### 3. テスト側の辞書追従

Production実装が理解できる語へテスト文言を変更してPASSさせてはならない。

例:

```text
NG: 「それなりに」をProduction markerに存在する「そこそこ」へ変更する
```

未対応の自然な言い換えが見つかった場合、Production辞書またはテストを語彙追加で合わせるのではなく、semantic boundaryそのものを修正する。

## 許容対象

有限文字列集合の使用自体を禁止するものではない。禁止対象はopen-ended自然言語のsemantic authorityである。

以下は許容する。

### A. Typed protocol / schema / enum

- JSON Schema keyword
- enum value
- canonical activity ID / operation ID
- API field name
- configuration key
- internal error code / trace label

これらは自然言語ではなく閉じたprotocol vocabularyである。

### B. Security / redaction

- secret key名
- token prefix
- credential URI pattern

機密値を隠すための検出は自然言語意味判定ではない。

### C. 語彙そのものがdomain dataである機能

例: しりとりの単語辞書、発音辞書。

ただし、その辞書を一般会話のintent/state/claim判定へ再利用してはならない。

### D. 非semanticな構文処理

- JSON抽出
- whitespace正規化
- schema parse
- punctuationを表示/segment用途に扱う

ただし、`?`があるからsemantic questionである、というように構文特徴だけを意味の正本へ昇格させてはならない。

## 正規アーキテクチャ

open-ended自然言語は、担当する意味解析境界でtyped structureへ変換する。

```text
Natural Language
      ↓
Semantic Interpreter / Appraisal
      ↓
Typed semantic result
      ↓
Deterministic Runtime Validation
```

Runtimeの決定論的検証対象はtyped structureとauthority/factであり、自然文の語彙ではない。

### User Input

```text
user text
→ Input Meaning Interpreter
→ StructuredInputMeaning
→ deterministic schema / authority validation
```

Runtimeは同じuser textを語彙辞書で再分類しない。

### Character Speech

```text
SemanticUtterancePlan
→ Character Language Realizer
→ Character speech
→ independent Realization Semantic Interpreter / Validator
→ typed realized semantics
→ Runtime compares typed semantics with SemanticUtterancePlan
```

Character自身の自己申告だけを正本にせず、独立したsemantic verification境界を持つ。

### Execution / Capability Claims

```text
Character speech
→ independent claim semantic interpreter
→ typed Claim
→ DeterministicFactValidator
   compares typed Claim with ActivityExecutionResult / Capability facts
```

実行事実の照合は決定論的に維持するが、speech→Claim変換をregex辞書で行わない。

### Question / Topic Budget

```text
Character speech
→ semantic speech-act/discourse interpretation
→ typed directed_question_count / topic_transition
→ ResponseBudgetValidator
```

Budget値との比較は決定論的に行うが、質問・話題転換の抽出を日本語語尾辞書で行わない。

### Confirmation

```text
confirmation answer
→ Input Meaning / dedicated confirmation semantic interpreter
→ ConfirmationResolution
→ PendingConfirmation state transition
```

`はい/いいえ/...` の有限語彙照合を正本にしない。

## Fail-closedの原則

semantic interpreterが利用不能・schema invalid・低確信度の場合、有限語彙Fallbackへ戻らない。

安全上意味判定が必要な経路は:

- clarification / retryへ移る
- semantic verification unavailableとしてrejectする
- 構造検証のみであることを明示し、semantic validatedと同一視しない

のいずれかとする。

「LLMが失敗したからregexで意味を推定する」は禁止する。

## Evidence spanの扱い

speech原文spanはdiagnostic/evidence anchorとして保持してよい。

Runtimeが検証してよいこと:

- spanがnon-emptyである
- spanが実際のspeechに存在する
- typed semantic resultとspanの参照関係がschemaとして成立する

Runtimeがしてはいけないこと:

- span内の単語を有限辞書へ照合してstate/intensity/certainty/predicateを判定する
- spanに特定語がないからsemantic facetをrejectする

meaningはsemantic interpreterのtyped resultとして検証する。

## Review Gate

自然言語を扱う新規・変更コードでは、レビュー時に以下を必ず確認する。

1. `speech / user_input / text / utterance`を有限語彙へ照合していないか
2. regexがsemantic classificationへ使われていないか
3. Fallback/Guard/Compatibilityとして同型実装を復活させていないか
4. typed semantic resultを利用できる既存境界を迂回していないか
5. test wordingをProductionの既知語へ寄せていないか
6. unseen paraphraseを含む検証があるか

## Architecture Test方針

静的監査では、semantic decision moduleについて以下を検出する。

- 自然語literal collectionと`in/startswith/endswith`の組み合わせ
- `re.compile`結果を`user_input/speech/text/utterance`へ適用
- `MARKER/KEYWORD/PHRASE/SYNONYM/ALIAS`等の語彙テーブル

ただしprotocol/security/domain lexical dataは明示的な理由付き例外として管理する。

例外は「モジュール単位の無条件除外」ではなく、用途と責務を限定する。

## 既知の是正対象

Issue #288開始時点で少なくとも以下を是正対象とする。

- `app/runtime/character_realization_validator.py` の `_EXPLICIT_INTENSITY_MARKERS`（未統合 #229 stack）
- `app/runtime/response_budget_validator.py` の質問/話題転換regex
- `app/runtime/response_claim_validator.py` のclaim/経験/身体完了/capability等regex・marker
- `app/runtime/pending_confirmation.py` のConfirmationResolver自然語regex
- `app/core/plugins/user_request.py` のfinite semantic fallback
- `app/runtime/activity_matcher_resolver.py` のlegacy start/stop marker adapter
- `app/domain/conversation_utterance_policy.py` のacknowledgement lexical compatibility判定

監査で追加候補が見つかった場合も同じ基準で分類する。

## 検証順序

```text
Policy / Audit
→ Unit: typed semantic boundaries
→ Adjacent: interpreter → deterministic validator
→ Regression: affected legacy guarantees
→ Lab / real LLM variation tests
→ System Verification
```

有限辞書を撤去するだけで既存安全保証を失わせず、意味解釈責務を正しい層へ移してから旧matcherを削除する。
