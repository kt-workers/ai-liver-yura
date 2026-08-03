# 入力意味・内部司令 Runtime Guard設計 v1.0.5

## 1. 目的

Internal Directive Plannerの実OpenAI検証で、現在の気分への直接質問に対する会話制御は適切だった一方、`response_goal`と`content_requirements`が抽象的な回答方針だけに留まり、実際のEmotion／Drive値がCharacter LLMへ十分に伝わらない例を確認した。

対象入力では次の値が与えられていた。

- `emotion.joy=0.58`
- `emotion.calm=0.74`
- `emotion.amusement=0.22`
- `drive.curiosity=0.61`

しかしPlanner候補は「現在の気分について直接的で簡潔に答える」とだけ指定し、落ち着き、明るさ、好奇心の強度を回答内容へ拘束していなかった。このままではCharacter LLMが内部状態と矛盾する感情を生成できる。

本設計では、内部状態への直接質問に対し、PlannerとCore Validatorの両方が現在値を具体的な回答根拠として搬送する。

## 2. 対象判定

次を内部状態への直接質問として扱う。

- `structured_input_meaning.expected_response=direct_answer`
- `target.type`が`internal_state`または`agent_internal_state`
- `target.id`が次のいずれか
  - `current_feeling`
  - `current_mood`
  - `current_emotion`
  - `mood`
  - `feeling`

既存の個別対象である`joy`、`amusement`、`anger`、`current_desire`も従来どおり扱う。

## 3. Plannerの責務

現在の気分全体が対象の場合、Plannerは抽象的な方針だけを返してはいけない。

- `internal_state.emotion`から値の高い1〜2項目を選び、`response_goal`へ具体的に含める
- `content_requirements`へ根拠となる項目名と数値を含める
- 次の目安で強度を言語化する
  - 0.70以上: 強め／高い
  - 0.45以上0.70未満: 中程度
  - 0.25以上0.45未満: 少し／弱め
  - 0.25未満: 低い。肯定的な主感情として誇張しない
- `drive.curiosity`は好奇心・関心として補助的に扱い、`joy`や`amusement`の代用にしない
- 「現在の気分に直接答える」のような抽象表現だけで完了しない
- 内部状態そのものが回答対象なので、必要な範囲の自己開示を許可する。ただし存在境界や安全制約を超えない

発話本文は引き続きCharacter LLMの責務とし、Plannerは自由文章のセリフを生成しない。

## 4. Core Validatorの責務

LLM候補が抽象的だった場合でも、Core Validatorは現在値を決定論的に追加する。

- `internal_state`と`agent_internal_state`を同一の内部状態対象として扱う
- 現在の気分全体では、Emotion evidenceを`content_requirements`へ追加する
- Drive evidenceは補助情報として追加し、Emotionとの区別を明示する
- 値が低いEmotionを強い感情として断定しないよう`forbidden_claims`を追加する
- 既存の個別感情・欲求質問の制約を維持する

Validatorは値を更新せず、回答に使用する根拠だけを補強する。

## 5. 存在境界との関係

現在の気分は内部状態への質問であり、通常は物理的身体経験を要求しない。したがって存在境界を回答本文へ毎回説明する必要はない。

ただし、Character LLMが根拠のない身体経験を付加することは禁止されたままとする。物理的身体状態を対象とする質問は、v1.0.3の存在境界Guardを引き続き適用する。

## 6. JSON契約と停止境界

- `InternalDirective`のJSON Schemaは変更しない
- クラウド検証ラボの停止位置は`internal_directive_planner`のまま
- Planner生出力では具体的なEmotion／Drive反映を確認する
- 完全RuntimeではCore Validatorが同じ根拠を決定論的に補強する

## 7. テスト

次を回帰テストで固定する。

- Planner Promptが`internal_state`と`agent_internal_state`の両方を対象にする
- `current_feeling`ではEmotion上位項目を`response_goal`と`content_requirements`へ具体化する指針を含む
- 強度目安と、低い値を誇張しない指針を含む
- `drive.curiosity`をEmotionの代用にしない指針を含む
- Validatorが`target.type=internal_state`を認識する
- Validatorが現在のEmotion／Drive evidenceを追加する
- 個別感情質問と存在境界Guardを回帰させない
