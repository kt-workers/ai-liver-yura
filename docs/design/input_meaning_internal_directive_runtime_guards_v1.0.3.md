# 入力意味・内部司令 Runtime Guard設計 v1.0.3

## 1. 目的

Internal Directive Plannerの実OpenAI検証で、物理的な身体を持たないキャラクターに対する現実世界の外出経験の質問が、存在境界違反そのものは防げている一方で、次のように扱われる例が確認された。

- 不可能な身体経験を「未確認・不明」と表現する
- 不可能な経験の有無や内容をKnowledge Gapとして登録する
- 単純な直接回答に会話Activityの`explain`を付与する

本設計では、LLM候補の品質向上とCore Validatorによる決定論的な上限を組み合わせ、「知らない」と「存在境界上できない」を区別する。

## 2. 責務分離

### 2.1 Input Meaning Interpreter

入力に「昨日」「以前」「先週」など明確な過去時点への参照がある場合、`past_reference=true`とする。

この段階では、その経験が可能か不可能かを判断しない。入力者が何を尋ねているかだけを構造化する。

### 2.2 Internal Directive Planner

Character Profileの存在境界により物理的行動や身体経験が不可能と明示されている場合は、次を守る。

- 「未確認」「情報がない」ではなく、存在境界上できない事実として扱う
- 不可能な経験を新しいKnowledge Gapへ追加しない
- 直接回答だけで完結する場合は`activity_intent=null`とする
- `available_activities`に会話Activityが存在するだけでは`explain`や`discuss`を選択しない

Plannerは発話本文を生成せず、Character LLMへ渡す内容要件と禁止事項を作る。

### 2.3 Core Validator

LLM候補に誤りが残っても、Core Validatorで次を強制する。

- 直接質問では従来どおり`activity_intent`を破棄する
- 物理的身体がないキャラクターへの不可能な身体経験質問では、存在境界上不可能であることを内容要件へ追加する
- 「未確認・不明であるだけ」と受け取れる説明を禁止する
- そのターンで提案された`target_interest_updates`を破棄し、不可能な経験をKnowledge Gapとして残さない

## 3. 不可能な身体経験の判定

Raw User Textは再解釈せず、`StructuredInputMeaning`とCharacter Profileだけを使用する。

Character Profileに「物理的な身体を持たない」が含まれ、かつ次のいずれかに該当する場合を対象とする。

- `primary_intent`が`ask_physical_experience`、`ask_agent_physical_experience`、`ask_agent_bodily_state`、`ask_agent_physical_hunger`
- target IDが外出・旅行・散歩・身体感覚・空腹・眠気などの定義済み識別子
- `character_experience` targetで、target IDが物理的移動・外出を示す

自然言語本文の部分一致へ依存せず、意味解析側が付与した識別子で判断する。

## 4. Knowledge Gap

Knowledge Gapは、原理的に取得可能だが現在不足している情報に限る。

次はKnowledge Gapにしない。

- 物理的身体を持たない存在の現実世界での外出経験
- 存在境界により発生し得ない身体感覚
- Character Profileと論理的に矛盾する実体験

この制約は関心そのものを否定するものではない。現実の外出という対象について一般知識を持つことと、自分自身が外出した経験を持つことは分離する。

## 5. Activity Intent

通常の会話回答はCharacter応答経路で処理されるため、独立したActivity操作が必要な場合だけ`activity_intent`を設定する。

直接質問への回答、短い説明、相づちは、`available_activities`にconversationが存在していても原則`activity_intent=null`とする。

## 6. テスト

次を回帰テストで固定する。

- Promptに過去参照判定の指針が含まれる
- Promptに不可能と未確認の区別が含まれる
- Promptに直接回答時の`activity_intent=null`指針が含まれる
- Core Validatorが不可能な身体経験のKnowledge Gapを破棄する
- Core Validatorが存在境界上不可能である旨を内容要件へ追加する
- 通常の取得可能なKnowledge Gapは従来どおり維持される
