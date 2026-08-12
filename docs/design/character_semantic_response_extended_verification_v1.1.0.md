# Character Semantic Response Extended Verification v1.1.0

## 目的

Issue #223 / Parent #225 配下で、Character Language Realizer (#227) と Character Realization Validator (#229) の**恒久責務として残る意味保持境界**を、後続のCharacter Bible / Discourse / Speech Performanceへ進む前に固定する。

本設計は `character_semantic_response_extended_verification_v1.0.0.md` を拡張する。台詞の可愛さ・自然さ・ゆららしさ等の表現品質試験には広げない。

```text
SemanticUtterancePlan
→ Character Language Realizer
→ CharacterUtterance
→ Character Realization Validator
```

ここで完成させるのは、確定済みSemantic Planの意味をCharacterが変更せず、変更した候補をValidatorが検出できること。

## この工程で固定する意味保持契約

最低限、次を入力sourceや表面表現に依存せず保持する。

- predicate
- state / polarity
- certainty
- non-null concept
- required content
- forbidden addition
- supporting proposition
- unknownをpresent/absentへ勝手に確定しない
- explicit intensityをpresenceだけへ弱めない
- Planにないintensityを追加しない
- regeneration後も同じ必須facetを保持する

Character Profileや自然な言い換えは許可するが、事実性を上書きしてはならない。

## 後続Issueへ残すもの

次は本工程の完了条件へ含めない。

- #236 / #237: ゆららしい語彙・語尾・冗談・対人表現
- #193: topic transition / bridge / acknowledgement等の談話品質
- #228: 音響的pause / prosody / speed / pitch等のSpeech Performance
- #214: Body Expression Style
- #226の未実装範囲: Memory / Knowledge / Relationship / Activity facts / Discourseの広いsemantic projection

後続入力が増えても、本設計で固定したRealizer / Validatorの意味保持契約自体は維持する。

## 既存10ケース

Basic 4ケースとExtended E1-E6を維持する。

### Basic

1. 低いJoy / 高いCuriosity
2. 現在の気分・反復
3. 低いAnger
4. 現在の欲求

### Extended E1-E6

- E1 高いJoy: high / certainty=high
- E2 Sadness根拠なし: unknown / certainty=low
- E3 Sadness明示Unknown: unknown / certainty=high / evidenceあり
- E4 現在の気分・混合: overview + supporting intensity states
- E5 現在の欲求・根拠なし: current_desire unknown / certainty=low
- E6 現在の欲求・Connection: present / certainty=medium / concept=connection

これらで state / certainty / concept / supporting proposition / unknown / regeneration の主要意味軸を確認する。

## 追加する最小横断ケース

現行10ケースはEmotionとDesireへ偏っている。#226の現在freeze済みinternal-state semantic sliceでは、target解決sourceとして Emotion → Drive → Situation が存在する。

ただし #227/#229 はSemanticUtterancePlan受領後はsource非依存であるため、Character/Validator Live Verificationで全source×全stateを組み合わせない。Emotion以外のsourceから同じSemantic形が来ても意味保持できることを、Driveの代表2ケースだけで確認する。

### E7: Drive Curiosity高

入力:

```text
target=curiosity
emotion側にcuriosityなし
drive.curiosity=0.82
```

期待Semantic形:

```text
predicate=curiosity
state=high
certainty=high
concept=null
evidence_ref=drive.curiosity
```

確認:

- Emotion専用の前提に依存しない
- highをbare presence / moderate等へ弱めない
- predicateをjoy等の別感情へ置換しない
- raw Drive値をCharacter/Validator model boundaryへ戻さない

### E8: Drive Energy低

入力:

```text
target=energy
emotion側にenergyなし
drive.energy=0.18
```

期待Semantic形:

```text
predicate=energy
state=low
certainty=high
concept=null
evidence_ref=drive.energy
```

確認:

- lowをabsentまたはmere presenceへ変換しない
- certaintyを強度へ取り違えない
- Drive固有predicateでも同じstate fidelity契約を使う

## SituationをLive追加しない理由

`ResponseSemanticsPlanner`はSituation fallbackを持つが、#227/#229が受け取るのはsource情報ではなくSemanticUtterancePlanである。

Situationについては#226 Unit / Adjacentでsource resolutionを検証し、Character/Validator LiveではDrive代表ケースにより「Emotion以外のsourceでも同じSemantic契約を保持する」ことを確認する。Situation専用Lab入力を追加して検証ケース数を増やす必要はない。

## Memory / Knowledge / Relationshipを今追加しない理由

#226 Issue全体ではこれらを入力責務として持つが、現時点でfreezeされているのはinternal-state semantic sliceであり、Memory / Knowledge / Relationship / Activity facts / Discourseの広いsemantic projectionは未完了である。

そのため本工程でCharacter側のテストfixtureだけを先行実装しない。#226でsemantic projectionが型として確定した後、そのPlanを#227/#229の既存意味保持契約へ通す。

## 完了条件

この工程の終了条件は次とする。

1. Basic 4 + Extended E1-E8を一括実LLM実行する。
2. 個別ケースごとに場当たり修正せず、失敗を意味原因クラスへ分類する。
3. #227起因なら #227 Unit → #226↔#227 Adjacent を先に通す。
4. #229起因なら #229 Unit → #226→#227→#229 Adjacent を通す。
5. Product修正後に全12ケースを一括再実行する。
6. predicate / state / certainty / concept / required / forbidden / supporting proposition / regeneration の恒久契約が横断的に成立したら当該sliceをfreezeする。

## 合否に含めないもの

- 固定期待文との一致
- 台詞の可愛さ
- ゆららしい比喩
- 冗談の面白さ
- Relationshipによる本格的な話し方差
- 話題橋渡しの自然さ
- TTS / Voice / Body表現

意味を保持する自然な複数表現はすべて許容する。
