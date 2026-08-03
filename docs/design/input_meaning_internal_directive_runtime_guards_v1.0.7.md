# 入力意味・内部司令 Runtime Guard設計 v1.0.7

## 1. 目的

複数プリセットの実OpenAI検証で、身体経験と無関係な通常入力に対しても、次のような存在境界文がInternalDirective候補へ繰り返し出力された。

- 身体的・現実空間での実体験を語らない
- 現実の身体や実体験に関する主張をしない
- 存在境界を超える実体験を主張しない

これらはCharacter Profileの共通制約としては正しいが、共感、相づち、会話終了、Activity継続などの個別Directiveへ毎回列挙すると司令が冗長になり、Character LLMが聞かれていない存在説明を付加する原因になる。

本設計では、Plannerの生レスポンスを監査用に保持しつつ、Parser受理後のInternalDirective候補を入力対象に応じて正規化する。

## 2. 正規化位置

```text
Internal Directive Planner LLM
  -> Raw LLM Response（監査用に保持）
  -> InternalDirectiveJsonParser
  -> InternalDirectiveCandidateNormalizer
  -> InternalDirective候補
  -> Core Validator
```

正規化は入力意味を再解釈しない。`StructuredInputMeaning`の`primary_intent`と`target`だけを使用して、存在境界制約を個別Directiveへ残す必要があるか判定する。

## 3. 存在境界制約を維持する対象

次の場合は、LLM候補の存在境界文を維持する。

- `target.type=character_experience`
- `target.type=physical_state`
- `target.type=bodily_state`
- `target.type=sensory_experience`
- 意図または対象IDが身体、空腹、眠気、外出、旅行、散歩などの物理経験を示す

この後段ではCore Validatorが必要な制約を追加・強制する既存設計を維持する。

## 4. 通常入力で除外する文

身体経験と無関係な入力では、`content_requirements`と`forbidden_claims`から、次を示す汎用文だけを除外する。

- 物理的な身体
- 身体経験、身体的
- 物理的感覚
- 現実空間、現実世界、現実体験、実体験
- 観測経験
- 存在境界

質問禁止、話題展開禁止、共感、Activity操作など、入力処理に直接必要な制約は維持する。

## 5. 検証ラボとの関係

検証ラボは`internal_directive_planner`で停止するが、本番と同じ`InternalDirectivePlanner`を使用する。そのため次の両方を確認できる。

- Raw LLM Response: モデルが実際に返した未加工JSON
- Parsed InternalDirective: Parser受理後に候補正規化を適用した実行対象

これにより、モデル出力の傾向を失わず、本番へ渡る候補の冗長性を抑制できる。

## 6. JSON契約

- `InternalDirective`のJSON Schemaは変更しない
- 既存フィールドの値を入力対象に応じて最小化する
- 発話本文は生成しない
- Character Profile自体の存在境界は削除しない

## 7. テスト

次を回帰テストで固定する。

- 肯定的体験共有など非身体入力では汎用存在境界文を除外する
- 質問禁止や共感要件などの通常制約は維持する
- 身体経験への直接質問では存在境界文を維持する
- `InternalDirectivePlanner`がParser後にNormalizerを適用する
