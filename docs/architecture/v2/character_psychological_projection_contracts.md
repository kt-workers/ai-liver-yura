# V2 Character Psychological Projection Contracts

Owner Issue: #355
Parent: #324
Upstream Character content: #354 / PR #390
Related canonical: `docs/architecture/v2/character_projection_contracts.md`
Status: Canonical Supplement

## 1. Purpose

#354で正本化した星波ゆらの精神構造を、固定Trait一覧へ退化させずRuntimeへ安全に投影するための補足契約を定める。

対象となる精神構造は次の7層である。

1. 本質的傾向
2. ホタルイカ由来の深層傾向
3. 形成史
4. 学習された信念・価値観
5. 自己モデル・物語的自己
6. 特徴的な適応傾向
7. 現在状態・Situation・意味づけ

Layers 1-6は比較的安定したCharacter Definition側の原因構造、Layer 7はlive Runtime State側の変動構造として分離する。

## 2. Core invariant

人格は次のような固定対応表として実装しない。

```text
Trait -> reaction
Emotion -> phrase
Fear -> pose
Lose -> retry
Praise -> blush
```

正規モデルは次である。

```text
Character causal structure (Layers 1-6)
+ current Internal State
+ current Relationship
+ Memory evidence
+ Goal / Commitment
+ Attention / Focus
+ current Situation / Appraisal
-> Executive / Speech / Bodyでその時点の表出が生じる
```

Character Definitionは反応結果のAuthorityではなく、その反応が生じやすくなる原因側evidenceを提供する。

## 3. Static / dynamic boundary

### 3.1 Character Definition側に置くもの

Layers 1-6のうちHuman VerificationまたはCharacter authoringで人物設定として確定・候補化された比較的安定した内容。

### 3.2 Runtime State側に置くもの

Layer 7はCharacterDefinitionへ保存しない。

少なくとも次は各Runtime Authorityのcurrent stateを利用する。

- Emotion / Desire / Drive / Motivation: Appraisal/Internal State (#327)
- Relationship current state: Internal State / Relationship owner
- Goal / Commitment: #366
- Attention / Focus / Turn: #333
- current Activity / Execution facts: #329
- current Situation / subjective meaning: Input Meaning + Appraisal
- ongoing episodic/semantic evidence: Memory #332 / Reflection #364

Character Profileがこれらを複製・永続化・推測生成してはならない。

## 4. Layer-to-schema mapping

初回V2 CharacterDefinition schemaは次のfirst-class categoryを持つ。

```yaml
identity: {}

dispositions: {}
deep_priors: {}
formative_history: {}
beliefs: {}
values: {}
self_model: {}
narrative_identity: {}
adaptations: {}

preferences: {}
language: {}
voice: {}
body: {}
```

### Layer 1: dispositions

本質的傾向。特定行動ではなく、注意・接近・警戒・満足等の方向性を表す。

例:
- exploration
- relationship_orientation
- autonomy
- mastery_orientation
- sensitivity

### Layer 2: deep_priors

ホタルイカ由来を含む、本人にも完全には説明できない深層の親和・警戒・注意bias。

例:
- affinity_to_small_low_threat_targets
- vigilance_to_large_powerful_targets
- survival_threat_fear_priority

### Layer 3: formative_history

人物形成上重要と人間が明示的に正本化した形成上の節目。

これはMemory Storeの生Episodic履歴ではない。

- raw conversation logを保存しない
- ongoing episodeを自動昇格しない
- Reflectionが直接CharacterDefinitionを書き換えない
- Character authoring / Human Verificationを経た形成史だけを置く

### Layer 4: beliefs / values

経験等から形成された比較的安定した世界理解・自己規範・価値。

`beliefs`と`values`を区別する。

- belief: 世界・自分・関係等をどう理解しているか
- value: 何を大切・望ましいと評価するか

現在の気分や一時的な意見を保存しない。

### Layer 5: self_model / narrative_identity

- `self_model`: 自分をどういう存在・能力・境界を持つ主体と理解するか
- `narrative_identity`: 形成史をどのように自分の物語として意味づけているか

実際に存在しない経験を物語として捏造してはならない。

### Layer 6: adaptations

Layers 1-5と経験から形成された、比較的安定した対処・対人・自己開示等の傾向。

例:
- weakness_disclosure_tendency
- social_distance_tendency
- failure_coping_tendency

禁止:

```text
if fear then hide weakness
if loss then retry
if praise then avert gaze
```

Adaptationは条件付き実行ruleではなく、Appraisal / Executive / Speech / Bodyが参照できる傾向evidenceとする。

### Layer 7: live dynamic state

CharacterDefinition schemaへcategoryを作らない。

Layer 7をstatic Profileへコピーした時点でAuthority違反とする。

## 5. Causal reference contract

7層を単なる独立リストへ平坦化しないため、Character facetは任意の`basis_refs`を持てる。

```yaml
beliefs:
  growth_from_failure:
    state: confirmed
    value: "失敗を改善材料として捉えやすい"
    basis_refs:
      - dispositions.mastery_orientation
      - formative_history.first_success_after_learning
```

`basis_refs`は説明可能な形成根拠・影響元を表す。

### 5.1 Authority

- `basis_refs`は決定論的reaction ruleではない。
- ref先の存在だけでfacet valueを自動生成しない。
- LLMがrefから未確認のbelief/adaptationを自動確定しない。
- Runtime consumerはbasisをevidence/provenanceとして利用できるが、Goal/Action/Speech/Body結果を直接導出しない。

### 5.2 Validation

- facet IDはCharacterDefinition全文で一意。
- `basis_refs`は同一document内の既知facet IDだけを参照する。
- 自己参照は禁止。
- reference cycleは禁止。
- 心理層facetのbasisは原則として同層またはより内側の安定層を参照する。
- Layer 7 current stateへのstatic `basis_refs`は保存しない。
- unknown refはfail-closed。

同層参照は相互依存の表現を許すため使用可能だが、cycleは許可しない。

## 6. Runtime psychological view

#355はLayers 1-6を欠落なくtypedに提供するため、少なくとも`CharacterPsychologicalProfile`相当のread-only viewを持つ。

最低限の構造:

```text
CharacterPsychologicalProfile
- character_id
- schema_version
- definition_revision
- dispositions
- deep_priors
- formative_history
- beliefs
- values
- self_model
- narrative_identity
- adaptations
```

各facetは既存certainty contractに従う。

- confirmed -> CONFIRMED(value)
- candidate -> UNRESOLVED
- unknown -> UNRESOLVED
- not_configured -> NOT_CONFIGURED

candidate textはRuntime factとして露出しない。

既存のspecialized profileは維持できる。

- CharacterLanguageProfile
- CharacterVoiceStyleProfile
- CharacterBodyStyleProfile
- CharacterSelfModelProfile
- CharacterDispositionProfile
- CharacterPreferenceValueProfile

ただしspecialized profileだけでLayers 1-6全体を表現できるとみなしてはならない。

## 7. Identity / preference / expression categories

`identity`、`preferences`、`language`、`voice`、`body`は7層精神構造そのものとは別のCharacter Definition facetとして維持する。

- identityは人物の基本的自己定義を提供する
- preferencesは比較的安定したaffinityを提供する
- language/voice/bodyは表現Styleを提供する

これらが精神構造から形成された設定である場合は`basis_refs`でLayers 1-6へ関連付けられる。

例:

```yaml
body:
  motion_softness:
    state: confirmed
    value: "soft"
    basis_refs:
      - dispositions.sensitivity
```

ただしこのrefからPoseやjoint angleを導出しない。

## 8. Runtime composition boundary

`CharacterPsychologicalProfile`だけで現在の反応を生成しない。

下流では必要に応じて次を別Authorityから同時に読む。

```text
CharacterPsychologicalProfile
+ InternalStateSnapshot
+ Appraisal facts
+ Relationship current state
+ MemoryEvidence
+ GoalContextView
+ AttentionFocusView
+ current execution/situation facts
```

### Executive

Character evidenceは選択・評価材料になり得るが、Executive Goal/Action Authorityを奪わない。

### Speech

Character psychological evidenceはSpeech Semanticsで確定したWhat-to-sayを変更しない。Character LanguageではHow-to-sayの人格的一貫性へ利用できる。

### Body

Character psychological evidenceとBody StyleはExpression Contextへ影響できるが、Pose/joint/presetを直接出力しない。

### Appraisal

本質・Deep Prior・Belief・Value等は主観評価の原因evidenceとして利用可能。ただしCharacterProfileがcurrent Emotionを直接設定しない。

## 9. Formation history vs Memory

Formation HistoryとMemoryを明確に分離する。

```text
Runtime experience
-> Memory Candidate / Store / Reflection
-> 必要に応じてHuman Character authoring判断
-> confirmed formative history / belief / narrative identity update
```

Memoryイベントが発生しただけでCharacter Definitionを自動mutationしない。

将来Character形成の自動化を行う場合も、別のtyped authoring/approval contractを設計してから導入する。

## 10. Schema compatibility during PR #419

本契約はPR #419がV2 trunkへ初回mergeされる前のDesign correctionである。

V2 trunkにはCharacterDefinition schema version 1がまだreleaseされていないため、今回のLayers 3/4/5/6追加は**初回schema version 1の完成形として修正する**。

不要なschema_version 2 migrationは作らない。

一度schema version 1がtrunkへmergeされた後に互換性を壊す変更を行う場合はversionを上げる。

## 11. Required regression

### Layer completeness

- dispositionsを投影できる
- deep_priorsを投影できる
- formative_historyを投影できる
- beliefsとvaluesを別々に投影できる
- self_model / narrative_identityを投影できる
- adaptationsを投影できる
- Layer 7 dynamic stateをCharacterDefinitionへ入力できない

### Causal refs

- valid basis_refsを保持
- unknown ref reject
- self ref reject
- cycle reject
- static documentからcurrent Emotion/Goal/Relationship refを作れない
- basis_refsからreaction commandを生成しない

### Authority

- Formation History != Memory Store
- Belief/Value != current Emotion/Interest
- Adaptation != fixed reaction rule
- CharacterPsychologicalProfile != Executive Authority
- Character psychological data cannot modify SpeechSemanticPlan fact
- Character psychological data cannot emit Body Pose/joint command

### Change tolerance

- Character値の変更だけならCore algorithm変更不要
- formative historyの具体内容変更だけならschema変更不要
- belief/adaptationの具体内容変更だけならschema変更不要
- alternate Characterでも同一schema/projectorを利用可能

## 12. Review findings integrated with this correction

PR #419 current reviewで残っている次の指摘も同一修正lineageで閉じる。

1. Domain APIを直接構築した場合もVoice/Bodyの許可facet境界を迂回できないよう、category-specific schema invariantをDomain側でも共有する。
2. hash不能なYAML mapping key等、invalid YAML/schema入力を未処理`TypeError`として漏らさずtyped load failureへ正規化する。

Adapterだけに安全境界を置かず、Domain constructorとLoader双方で同一contractを守る。

## 13. Done condition for this amendment

- 本文書を#355 canonical supplementとして記録
- CharacterDefinition schemaがLayers 1-6をfirst-classに表現可能
- optional causal `basis_refs`を型付き・cycle-freeで保持
- `CharacterPsychologicalProfile`相当のtyped viewを提供
- Layer 7はdynamic Authority側に残す
- current P1/P2 review findingsを同一headで修正
- targeted / full pytest / Ruff / strict Mypy / compileall / diff-check PASS
- exact-head CI PASS
- current headへの独立再レビューでblocking finding 0
