# V2 Character Definition / Projection Contracts

Owner Issue: #355
Parent: #324
Upstream Character content: #354 / PR #390
Status: Canonical Design

## 1. Purpose

`#354` が所有する Human-readable Character Definition を、Runtime が安全に利用できる typed Profile へ投影するための正規契約を定める。

Character の具体値を Python code / Prompt template / Voice engine parameter / Body Pose preset へ焼き込まない。年齢感、性別表現、一人称、Preference、Belief、Voice Style、Body Style 等が後から変更されても、既存 facet category の範囲なら Core algorithm / schema のコード変更を要求しない。

## 2. Authority hierarchy

Character 情報は次の三層を分離する。

```text
Human-readable Character Bible (#354)
        semantic authority
             ↓ explicit authoring sync
Machine-readable CharacterDefinition document
        structured runtime input
             ↓ deterministic projection
Typed Runtime Profiles (#355)
        derived read-only views
```

### 2.1 Human-readable Character Bible

- 人物設定の意味上の最終 Authority は `#354` の Character Bible。
- 人物像、設定理由、形成史、未決定事項、Verification 判断を人間が理解・レビューできる形で保持する。
- Markdown 本文を Runtime が自然言語解析して Profile 化してはならない。
- Runtime 起動時に LLM を使って Bible を構造化してはならない。

### 2.2 Machine-readable CharacterDefinition document

Character Bible のうち Runtime が利用する facet を、人間が明示的に同期する versioned structured document とする。

- production Character content の ownership は `#354`。
- `#355` は document schema / loader contract / projector を所有する。
- 現行 repository の production data location は `character_definitions/v2/<character_id>.yaml` とする。
- storage path 自体を Domain Authority にしない。将来 DB / package resource 等へ置換しても Domain contract は変えない。
- Character Bible と structured document が矛盾する場合は **Bible が勝ち、structured document を修正するまで release / verification を進めない**。
- structured document は Runtime convenience のための mirror / compile input であり、人物設定の意味を独自に追加しない。

### 2.3 Typed Runtime Profiles

Runtime Profile は CharacterDefinition から決定論的に生成される derived view である。

- Profile を編集して Character Definition を変更しない。
- Profile を persistence の人物設定正本にしない。
- current Emotion / Desire / Drive / Relationship / Goal / Attention / Interest / Memory current fact / Activity state を Profile へ保存しない。
- Layer 7を表すfacet IDおよび`current_`接頭辞のfacet IDは、CharacterDefinition schemaでfail-closedに拒否する。
- Profile は What-to-say / Actual Fact / Executive decision の Authority を持たない。

## 3. CharacterDefinition document format

Format は YAML とし、schema version を必須にする。Loader は YAML syntax を読むだけであり、自由文 Markdown の semantic parsing は行わない。

最低限の top-level contract:

```yaml
schema_version: 1
character_id: yura
definition_revision: 1
authority:
  bible_path: docs/character/v2/yura_character_bible.md
  owner_issue: 354

identity: {}
dispositions: []
deep_priors: []
values: []
preferences: []
self_model: {}
language: {}
voice: {}
body: {}
```

### 3.1 Versioning

- `schema_version`: document shape / facet category contract の version。
- `definition_revision`: Character content の monotonically increasing revision。
- 具体値だけの変更では `definition_revision` を増やし、`schema_version` は変えない。
- 新しい facet category、field semantics、Authority boundary が必要な場合だけ schema design を更新する。
- Runtime Profile は `character_id / schema_version / definition_revision` を provenance として保持する。

## 4. Field certainty contract

未確認値を default で事実化しないため、CharacterDefinition の configurable field は certainty state を明示する。

```yaml
first_person:
  state: candidate
  value: "ゆら"
```

許可 state:

- `confirmed`: Human Verification 済み。`value` 必須。
- `candidate`: 候補値。`value` 必須だが Runtime の Character fact として使用禁止。
- `unknown`: 未決定。`value` 禁止。
- `not_configured`: 当該 Character では現在使用しない。`value` 禁止。

Validation は fail-closed とする。

- `confirmed` / `candidate` で value 欠落 → invalid。
- `unknown` / `not_configured` に value が存在 → invalid。
- unknown field / unknown state / duplicate id → invalid。
- typo や余剰 key を黙って無視しない。
- schema validation failure 時に guessed default Profile を生成しない。

## 5. Candidate / unknown leakage prohibition

Authoring document は candidate value を保持できるが、production Runtime Profile へ candidate の内容を Character fact として露出してはならない。

Projection result の field availability は次へ正規化する。

- `confirmed` → `CONFIRMED(value)`
- `candidate` → `UNRESOLVED`（candidate value は Runtime consumer へ渡さない）
- `unknown` → `UNRESOLVED`
- `not_configured` → `NOT_CONFIGURED`

Runtime consumer が `candidate` と `confirmed` を取り違えないことを contract test で保証する。

Authoring / diagnostics UI が candidate text を表示する必要がある場合は、Runtime Profile とは別の authoring read model を使う。

## 6. CharacterDefinition semantic categories

### 6.1 Identity / Self Model

Character-specific な自己定義のみを保持する。

例:
- display name / reading
- age impression
- gender expression
- self identification
- virtual / AI identity の Character-specific statement

System-wide truthfulness / execution fact / sensory evidence rule を Character content として再定義しない。

### 6.2 Dispositions / Deep Priors / Values

固定 reaction rule ではなく、比較的安定した原因側の character evidence を保持する。

各 item は最低限:

```text
id
state
value / description
optional tags
```

を持つ。

禁止:
- `fear -> pose_x`
- `lose -> retry`
- `praise -> blush`
- Emotion 名から固定台詞 / fixed Motion を選ぶ rule

### 6.3 Static Preferences

恒常的 Preference / affinity を保持できるが、current interest や「今それを話したい」を表してはならない。

Preference は current Attention / Goal / Speech を直接 mutate しない。

### 6.4 Language

Language Profile へ投影可能な engine-independent facet を保持する。

例:
- first person
- addressing / register
- softness / directness tendency
- rhythm / response-length tendency
- humor / teasing tendency
- hesitation tendency

固定 sentence ending / fixed phrase list を Character Authority にしない。

### 6.5 Voice

Voice engine parameter ではなく人物的な高レベル Style を保持する。

例:
- baseline softness
- calmness / energy tendency
- pacing tendency
- emotional expressiveness tendency

禁止:
- speaker ID
- provider pitch numeric parameter
- engine-specific speed / volume value

provider parameter への変換は Infrastructure Adapter responsibility。

### 6.6 Body

Body Motion の高レベル Style だけを保持する。

例:
- motion softness
- amplitude tendency
- continuity tendency
- compact / expansive tendency
- symmetry / asymmetry tendency
- gaze / head / posture expression tendency

禁止:
- joint angle
- Pose name
- Gesture preset
- Home / Neutral reset
- solver / IK rule

Skeleton / DOF / joint limits / IK / Balance / realtime continuity は Body architecture responsibility。

## 7. Runtime Profile set

#355 は最低限次の immutable typed view を提供する。

- `CharacterLanguageProfile`
- `CharacterVoiceStyleProfile`
- `CharacterBodyStyleProfile`
- `CharacterSelfModelProfile`
- `CharacterDispositionProfile`
- `CharacterPreferenceValueProfile`

共通 metadata:

```text
character_id
schema_version
definition_revision
```

Profile は existing V2 convention に合わせ、原則 `frozen dataclass / slots=True` の immutable contract とする。

## 8. Loader / projector responsibility

### Loader

YAML Adapter responsibility:

```text
YAML bytes
→ syntax parse
→ strict schema validation
→ immutable CharacterDefinitionDocument
```

- PyYAML 等 provider-specific object を Domain へ露出しない。
- file path / package resource / DB 等の storage mechanism は Adapter 外側へ閉じ込める。
- missing / invalid / unsupported schema は typed failure。

### Projector

Domain / usecase sideの pure deterministic function とする。

```text
CharacterDefinitionDocument
→ CharacterProjectionBundle
   ├─ LanguageProfile
   ├─ VoiceStyleProfile
   ├─ BodyStyleProfile
   ├─ SelfModelProfile
   ├─ DispositionProfile
   └─ PreferenceValueProfile
```

Projector は:
- LLM を呼ばない。
- payload text を再解釈しない。
- candidate を confirmed へ昇格しない。
- dynamic state を生成しない。
- Goal / Speech semantics / Activity を決めない。

## 9. Ownership between #354 and #355

### #354 owns

- Character Bible
- Human Verification
- production CharacterDefinition content document
- confirmed / candidate / unknown の人物設定判断
- runtime-relevant content change 時の structured document 同期

### #355 owns

- CharacterDefinition schema
- certainty model
- strict loader contract
- deterministic projection logic
- Runtime Profile types
- schema / projection tests

この分離により #355 の mechanism 実装は #354 の全 content 確定を待たずに進められる。

## 10. Development sequencing while #354 is Verification

#354 / PR #390 が Human Verification 中でも #355 は次を実装可能:

1. schema / domain types
2. strict YAML loader
3. deterministic projector
4. generic fixtureによる Unit tests
5. alternate character fixtureによる schema generality test
6. candidate / unknown leakage regression
7. no-code-change content substitution test

production `yura.yaml` の最終内容は #354 owner が管理する。#355 の実装完了条件を「全ゆら設定が確定済み」にしない。

#354 が後から既存 category 内の値を変更した場合:

```text
Bible update
+ CharacterDefinition data update
→ definition_revision increment
→ Runtime restart/reload
→ same code / same schema
```

で反映可能であること。

## 11. Failure behavior

- CharacterDefinition missing → typed unavailable / degraded。別Character値を勝手に採用しない。
- invalid schema → fail closed。partial guessed Profileを生成しない。
- unsupported schema version → typed incompatible failure。
- unresolved field → Profileでは UNRESOLVED。default Character factを生成しない。
- optional Profile facet不足で Core全体を停止するかは Composition / consumer policyで決める。Projection layerが勝手に invented valueを補わない。

## 12. Required tests

### Schema / loader

- valid document
- unknown top-level / nested key reject
- unsupported schema version
- duplicate item id
- invalid certainty state
- confirmed without value reject
- candidate without value reject
- unknown/not_configured with value reject
- malformed YAML typed failure

### Projection

- confirmed value only projects as fact
- candidate value does not leak
- unknown → UNRESOLVED
- not_configured → NOT_CONFIGURED
- all profiles preserve character/schema/definition revision
- dynamic state fields cannot appear in CharacterDefinition/Profile contract
- engine-specific Voice value reject / absent by schema
- Body Pose/joint/preset value reject / absent by schema

### Change tolerance

- same schema + different Character values → no code/schema change required
- same projector with another Character fixture works
- changing only data changes Profile values/revision, not contract type

### Authority regression

- Character Profile cannot change SpeechSemanticPlan facts
- Preference cannot synthesize current Interest
- Disposition cannot synthesize current Emotion/Goal
- Character Body Style cannot emit joint angle / Pose command

## 13. Non-goals

- Character Bible全文の自動Markdown parser
- LLMによる起動時Character extraction
- Character contentの自動採否
- Human Verificationの自動化
- Voice provider parameter tuning
- Body Motion generation / IK / realtime controller
- SpeechSemanticPlan生成
- Character Language realizationそのもの（#330）

## 14. Design Gate acceptance

#355 implementation は次を満たしてから開始する。

- 本文書が canonical として #355 に記録されている。
- active lineage が `feature/v2-character-projection` 1本である。
- V2 trunk/base SHA drift がない、または再同期済みである。
- Project Status を Design待ち Blocked から In progress へ戻す。

以後は Design → Code を維持する。
