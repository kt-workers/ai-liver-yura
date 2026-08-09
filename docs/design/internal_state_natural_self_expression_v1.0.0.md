# 内部状態を自然な自己表現へ反映する設計 v1.0.0

## 目的

`今どんな気分？`、`楽しい？`、`怒ってる？`、`何かしたい？`のような
内部状態への直接質問で、Characterが
`neutral`、`calm=0.74`、`中立的な気分`などの内部モデルを診断結果のように
自己説明しないようにする。

内部状態はCharacter発話のevidence/causeであり、content requirementではない。

## 正規経路

```text
Emotion / Desire / Drive
→ affective context
→ Interaction Intention / Interaction Expression
→ Character generation
→ 人物として自然な言葉・語調・発話量へ反映
```

Characterへは既存の`InternalStateAwareResponseContextBuilder`を通して
`ResponseContext.emotion`と`ResponseContext.drive`を渡す。このstructured stateは
本変更後も維持する。

## Internal Directiveの責務

Internal Directive Plannerはstructured Emotion/Driveを判断根拠として利用できる。
ただし`internal_state` / `agent_internal_state`への直接質問全般では、次を
`response_goal`、`content_requirements`、`forbidden_claims`へ発話内容として移さない。

- Emotion/Driveの内部キー
- 内部値や強度区分
- `Emotion evidence` / `Drive evidence`
- `中立的な気分`などの内部分類
- 状態名に対応する固定文や言い換え辞書

`response_goal`は「現在の内的状態に沿って、質問へ自然に直接答える」という
会話目的に留め、発話本文を先に作らない。

## 構造境界による正規化

LLM Plannerが内部状態を自然語へ変換したgoal/requirementを返す可能性がある。
自然語化後の文章を診断文らしさで判定することはできないため、CoreのValidatorは
内部状態への直接質問全般をtarget typeと発話行為で識別し、次を構造的に正規化する。

- `response_goal`を自然な直接回答の会話目的へ戻す
- Planner生成の`content_requirements`を採用しない
- Planner生成の`forbidden_claims`を採用しない
- existence boundary等のCore deterministic constraintを後から追加する
- target IDの固定一覧を使わず、将来追加される内部状態targetにも同じ境界を適用する
- 固定セリフへ置換しない

この正規化は感情語辞書、正規表現、日本語診断文分類を使用しない。
Characterは別経路のstructured Emotion/Drive、Interaction Intention / Expression、
conversation historyを使い、その場で発話を生成する。

## 2回目Verification追補: 個別状態を含む二重搬送

Input Meaningのtyped target修正後、13件すべてでtargetは正しく構造化された。一方、
current feelingへの6回の質問が完全に同じ文となり、joy / anger / current_desireでも
内部状態の具体値や自然語化済み説明が`content_requirements`へ搬送されていた。

```text
structured internal state
→ Plannerが状態を自然語の説明内容へ変換
→ 同じ具体的content requirementがCharacterを固定
→ diagnostic and repeated Character speech
```

このため個別状態質問を対象外とする旧判断を撤回し、内部状態への直接質問全般を
同じ構造境界の対象とする。`current_concern`、`loneliness`、`confidence`等の新しい
target IDにも追加実装なしで適用される。

旧evidence注入経路は廃止する。

- `joy=...`, `amusement=...`, `engagement=...`
- `現在のanger=...`
- `Drive evidence: {...}`
- 内部値を自然語へ変換するようCharacterへ要求するcontent requirement

内部状態をCharacterから隠すのではない。内部状態は別のstructured contextとして
維持し、答えの具体的な文章だけをInternal Directiveで先取りしない。

## 実環境Verification追補: Input Meaning target契約

初回の実環境Verificationでは、13件すべてのInput Meaning結果が
`input_speech_act=question`かつ`target=null`になっていた。これにより、次の経路で
Validatorの正規化が迂回された。

```text
Input Meaning target=null
→ current feeling normalization bypass
→ raw structured mood classification reused by Planner
→ diagnostic Character speech
```

`target`はNamed Entityだけを表すものではない。質問・request・command等が意味的に
対象としている状態、対象物、活動、行為、話題をtyped identityとして表す。
内部状態質問ではInput Meaning LLMが意味を次のcanonical targetへ正規化する。

- 現在の全体的な内的状態: `internal_state/current_feeling`
- 喜び・楽しさ: `internal_state/joy`
- 怒り: `internal_state/anger`
- 現在の欲求: `internal_state/current_desire`

これは日本語の固定文字列辞書、正規表現、Parserによるraw text再解釈ではない。
言い換えでも同じ意味なら同じtargetへ正規化し、曖昧参照はconversation history、
current topic、ongoing activity等の意味文脈から解決する。

意味上の対象を持つ`question`、`request`、`command`で`target=null`になった結果は
typed契約違反として受理しない。この違反に限り、Coreがtargetを決めるのではなく、
Input Meaning LLMへ欠落した意味対象を再構造化するよう一度だけ要求する。
`target=null`は本当に意味上の対象を持たない入力だけに限定する。

## PR #135から維持する目的

PR #135が目指した「内部状態をCharacterへ十分に搬送し、状態と矛盾しない回答を
生成する」という目的は維持する。

当時はInternal Directiveの`response_goal` / `content_requirements`を主な搬送先と
したが、現行因果設計ではstructured `ResponseContext`とInteraction Expressionが
その責務を持つ。このため旧Internal Directive発話要件経路だけを縮小し、内部状態の
取得やCharacterへのstructured搬送は削除しない。

## 維持する契約

- `self_disclosure_level >= 0.35`の直接回答許可
- question budget / new direction budget
- `ResponseContext.emotion` / `ResponseContext.drive`
- Interaction Intention / ExpressionからCharacter・Bodyへ至る因果経路
- conversation history
- physical hunger等へ後から追加されるexistence constraint

## Verification

複数の内部状態でcurrent feeling、joy、anger、current desire、current concernを
複数回確認する。

- 内部キー・数値・内部分類を読み上げない
- 診断レポート口調にならない
- 状態差が語調・内容・発話量へ自然に反映される
- 毎回同じ固定文にならない
- 質問へ直接答え、無関係な話題へ逃げない
- question budget誤判定が再発しない
- Input Meaning targetと`internal_state_guidance_normalized`を確認する
- physical hunger等でexistence constraintが維持される
