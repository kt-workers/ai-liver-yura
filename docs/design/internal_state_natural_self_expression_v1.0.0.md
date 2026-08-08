# 内部状態を自然な自己表現へ反映する設計 v1.0.0

## 目的

`今どんな気分？`のような現在の気分全体への質問で、Characterが
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
ただしcurrent feeling系では、次を`response_goal`や`content_requirements`へ
発話すべき内容として移さない。

- Emotion/Driveの内部キー
- 内部値や強度区分
- `Emotion evidence` / `Drive evidence`
- `中立的な気分`などの内部分類
- 状態名に対応する固定文や言い換え辞書

`response_goal`は「現在の内的状態に沿って、質問へ自然に直接答える」という
会話目的に留め、発話本文を先に作らない。

## 決定論的な正規化

LLM Plannerが旧形式の診断的なgoal/requirementを返す可能性があるため、Coreの
Validatorでcurrent feeling系だけを正規化する。

- `response_goal`を自然な直接回答の会話目的へ戻す
- 実際のstructured Emotion/Driveに含まれる内部tokenを発話要件から除く
- evidence marker、数値付き状態説明、状態名と強度区分を組み合わせた診断説明を除く
- 通常の日本語を単語単位で全面禁止しない
- 固定セリフへ置換しない

例えば`落ち着いて、短く答える`という通常の表現方針は保持できる。一方、
`落ち着きが強め`や`Emotion evidence: calm=0.74`は内部診断の搬送なので除く。

## PR #135から維持する目的

PR #135が目指した「内部状態をCharacterへ十分に搬送し、状態と矛盾しない回答を
生成する」という目的は維持する。

当時はInternal Directiveの`response_goal` / `content_requirements`を主な搬送先と
したが、現行因果設計ではstructured `ResponseContext`とInteraction Expressionが
その責務を持つ。このため旧Internal Directive発話要件経路だけを縮小し、内部状態の
取得やCharacterへのstructured搬送は削除しない。

## 対象外

- `楽しい？`、`怒ってる？`、`何かしたい？`など個別状態質問の既存契約
- `self_disclosure_level >= 0.35`の直接回答許可
- question budget / new direction budget
- Interaction Intention / ExpressionからCharacter・Bodyへ至る因果経路
- 状態名を固定セリフへ変換するテンプレート

## Verification

複数の内部状態で`今どんな気分？`と`何か気になることある？`を複数回確認する。

- 内部キー・数値・内部分類を読み上げない
- 診断レポート口調にならない
- 状態差が語調・内容・発話量へ自然に反映される
- 毎回同じ固定文にならない
- 質問へ直接答え、無関係な話題へ逃げない
- question budget誤判定が再発しない
