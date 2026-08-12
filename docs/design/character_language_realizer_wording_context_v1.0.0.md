# Character Language Realizer User Wording Context v1.0.0

## 目的

Character LLMを「何を言うか」の判断から外したまま、ユーザーが質問に用いた語彙・意味枠を自然な言語実現で保持する。

## 背景

Semantic Utterance Planが `predicate=joy, state=absent` を正しく生成していても、Character Language Realizerが内部接続用の英語ラベル `joy` を自然語の概念として再解釈すると、ユーザーの質問「楽しい？」に対して「うれしさはない」のように、近いが異なる概念へずれる可能性がある。

この問題は内部数値の混同ではなく、内部識別子をCharacterが語彙意味として再解釈していることが原因である。

## 責務境界

Character Language Realizerへ渡す情報を次の3系統に分ける。

1. Semantic Utterance Plan
   - 発言事実、state、certainty、禁止追加、budgetを決める唯一の正本。
2. Character Profile
   - 語尾、語彙選択、一人称、柔らかさ、言い淀み等のCharacter表現を決める。
3. User Wording Hint
   - ユーザーが質問対象をどの語彙・意味枠で表現したかを保持する限定的な言語参照。
   - 事実、内部状態、強度を推論する材料にはしない。

## User Wording Hint

Semantic経路のLLM Activity Contextには従来どおり `user_input` / `response_context` / raw Emotion / raw Driveを載せない。

Character/Validator Prompt Builderだけが `ResponseContext.user_input` から最大500文字のWording Hintを生成する。

```text
ResponseContext.user_input
  -> Prompt-only User Wording Hint
  -> Character Language Realizer / Realization Validator
```

これはLLM Activity Contextへraw入力を復活させるものではない。

## 優先順位

矛盾時の優先順位は次の通り。

```text
Semantic Utterance Plan > User Wording Hint > Character Profileによる自由表現
```

User Wording Hintは対象概念の語彙的・談話的な枠だけを保持する。状態の真偽や強度はSemantic Planから変更してはならない。

## predicate / target.id

`predicate` と `target.id` は内部状態・evidenceとの接続識別子であり、自然語の語彙指示ではない。

Character Language Realizerはこれらの英語ラベルから対象概念を再定義してはいけない。User Wording Hintが示す対象概念を、意味の近い別概念へ勝手に置き換えない。

## Validator

Character Realization Validatorも同じUser Wording Hintを参照し、以下を検証する。

- Semantic Planのpolarity/state/certaintyを保持している。
- User Wording Hintが示す質問対象の意味枠を、隣接する別概念へ置換していない。
- User Wording Hintを新しい事実の根拠として使用していない。
- raw Emotion/Driveやevidence pathを再解釈していない。

## 非目標

- 固定日本語フレーズ辞書を作ること。
- target idごとの言い換え表を作ること。
- raw Emotion/DriveをCharacterへ戻すこと。
- Character LLMに内部状態の意味判定を戻すこと。
- Speech Performanceの音響parameterをCharacterへ戻すこと。

## Verification

直接内部状態質問で以下を確認する。

1. Semantic Planは質問対象の内部状態について正しいstateを持つ。
2. Character Model Activity Contextにraw `user_input` / Emotion / Driveがない。
3. Character PromptにはUser Wording Hintがある。
4. 最終発話は質問対象の意味枠を保ち、近接する別概念へずれない。
5. Realization Validatorも同じ意味枠を検証する。
