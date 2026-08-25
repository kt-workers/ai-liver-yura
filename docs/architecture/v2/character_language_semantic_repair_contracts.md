# V2 Character Language Semantic-Safe Repair Contracts

Owner Issue: #330
Validation: #434
Related: #363
Parent canonical: `character_language_contracts.md`
Related canonical: `character_language_variation_contracts.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

Character Languageの目的は「複数候補を生成して最も多様な文を選ぶこと」ではない。

productionの基本動作は、確定済み`SpeechSemanticPlan`から**1つの自然な`CharacterUtterance`を生成すること**である。

#434 strict same-Plan 10-runではbounded prior awarenessによりexact-text variationは2/10 uniqueから10/10 uniqueへ改善した一方、#363 semantic acceptanceは10/10から8/10へ低下した。

REJECTされたactual utterance:

- `今日は少し涼しい感じだね。` -> `certainty_changed`
- `今日は少し涼しいみたい。` -> `certainty_changed`

この結果から、variation pressureはsemantic preservationより弱いquality objectiveとして扱い、productionをcandidate searchへ変えずにsemantic-safe repairだけを追加する。

---

## 2. Production generation policy

通常の発話準備では次を原則とする。

```text
SpeechSemanticPlan
  -> Character Language 1回生成
  -> CharacterUtterance commit
  -> #363 Semantic Verification
```

最初からN候補を生成しない。
候補ranking、best-of-N、variation最大化scoreを導入しない。

同一Planに対してprior realizationが存在しても、priorは弱いHow-to-say参考情報にすぎない。

- 自然で意味安全な別表現があれば重複を避けてもよい。
- 同じ表現が最も自然・安全なら再使用してよい。
- exact duplicate自体をfailureにしない。
- semantic preservation / naturalness > variation とする。

---

## 3. Semantic repair trigger

Character Languageのrepairは、**actual committed utteranceが#363でsemantic `REJECTED`になった場合だけ**開始できる。

### repair triggerになるもの

- polarity changed
- certainty changed
- degree changed
- execution status changed
- REQUIRED meaning missing
- FORBIDDEN meaning realized
- unsupported material content
- budget / self-disclosure等、#363がsemantic rejectionとして確定したもの

### repair triggerにしないもの

- Provider timeout
- #363 Provider failure
- #363 schema/transport/runtime failure
- verifier infrastructure unavailable
- latencyだけが高い
- variation不足だけ

#363自体が正常にsemantic判定できなかった場合、Character文を作り直して原因を隠してはならない。Verifier retry/fail-closedは#363側のpolicyで扱う。

---

## 4. Bounded repair count

v1 repair policyは次のとおりとする。

```text
initial generation: 1
semantic repair generation: max 1
maximum Character Language generations per presentation opportunity: 2
```

repair後も#363 `REJECTED`なら、そのpresentation opportunityではCharacter Languageを追加生成し続けない。

理由:

- best-of-N candidate search化を防ぐ
- latency/tokenの暴走を防ぐ
- semantic driftをvariationで追いかけ続けない
- failureを上流/orchestrationへ明示できるようにする

---

## 5. Conservative repair request

semantic repairは**同一のcommitted `SpeechSemanticPlan`**を使う。

以下を変更しない。

- semantic plan ID / candidate
- source decision / intent / event IDs
- revisions
- Character Profile revision
- relationship/discourse constraints
- model/reasoning policy（別の明示policyを選ぶ設計を将来追加しない限り）

v1 repairではvariation pressureを外すため、repair snapshotの`prior_realizations`は空にする。

```text
same SpeechSemanticPlan
same Character Profile
same constraints
prior_realizations = []
```

これはgeneric fallback phraseではない。
同じproduction Character Language LLMへ同じsemantic Authorityを再提示し、variation最適化だけを弱めた**保守的な再実現**である。

#363 rejection categoryを有限語句変換ルールへ変換しない。
`certainty_changed -> 「みたい」を禁止`のようなword/regex ruleは作らない。

current Plan自体がpolarity / certainty / degree / execution status等を既に保持しているため、repairではそのPlanを再度最優先で実現させる。

---

## 6. Prior realization acceptance rule

same-Plan repetition-awarenessへ渡すpriorは、semantic-invalidな出力をvariation historyとして残さない。

production orchestrationで#363が適用される経路では、prior候補にできるのは次だけとする。

```text
committed CharacterUtterance
AND
#363 SemanticAcceptance == ACCEPTED
```

`REJECTED` utteranceは:

- presentationしない
- future priorへ追加しない
- next repetitionのnegative referenceへ追加しない

#330 Domain自体は#363型をimportせずSemanticAcceptance Storeを検索しない。
**accepted-only selectionはcaller/orchestration ownership**とする。

#330が検証する既存provenance gate:

- same Plan
- same Character revision
- same constraint revisions
- bounded max count
- freshness

は引き続き維持する。

---

## 7. End-to-end state machine

```text
INITIAL
  |
  v
Character generation #1
  |
  v
CharacterUtterance commit
  |
  v
#363 verify
  |---------------------------|
  | ACCEPTED                  | REJECTED
  v                           v
presentation eligible     repair allowed
accepted prior eligible       |
                              v
                    Character generation #2
                    prior_realizations=[]
                              |
                              v
                         #363 verify
                         |          |
                         | ACCEPTED | REJECTED
                         v          v
                    presentation   STOP / fail closed
                    eligible       no more Character retry
```

#363 execution failureは上記`REJECTED` branchへ入れない。

---

## 8. #434 Lab responsibilities

#434はproduction candidate searchを模倣しない。

Labには2種類の測定を分離して残す。

### Variation characterization

同一Planを複数回生成して、モデルの表現分布を調べる品質試験。

- production本番回数を意味しない
- unique率はhard requirementではない
- semantic acceptanceとセットで観測する

### Production-flow repair verification

production相当の1-shot + bounded repairを検証する。

1. initial generation 1回
2. #363 verify
3. ACCEPTEDなら終了
4. REJECTEDならpriorなしでrepair 1回
5. #363再検証
6. repair後もREJECTなら終了

Exportではinitialとrepairを明確に区別し、repairを「候補2/10」のようなvariation candidateとして数えない。

---

## 9. Required regression

### Production policy

- semantic ACCEPTEDならCharacter generationは1回だけ
- semantic REJECTED時だけ最大1 repair
- repair後REJECTで3回目を生成しない
- #363 execution failureでCharacter repairしない
- variation不足だけでrepairしない

### Repair invariants

- repairはexact same Plan ID
- same Profile / constraints / revisions
- repair snapshotは`prior_realizations=[]`
- generic/fixed fallbackなし
- finite lexical correction tableなし

### Prior selection

- ACCEPTED utteranceだけprior candidateへ追加
- REJECTED utteranceはpriorへ追加しない
- accepted-only filterはcaller/orchestration ownership
- #330 Domainに#363 Store/importを導入しない

### #434 live

- initial acceptance rate
- repair invocation rate
- repair success rate
- final semantic acceptance rate
- Character generation count per presentation opportunity
- latency/token増加
- naturalness / Character fidelity

を測定する。

---

## 10. Explicit non-goals

本契約では次を行わない。

- best-of-N generation
- 10候補生成してranking
- uniqueness最大化
- lexical distance scorer
- finite語尾rotation
- synonym dictionary
- semantic rejection categoryごとの単語禁止表
- unbounded retry
- generic safe phrase fallback
- #363 semantic Authorityを#330へ移す

Character Languageは1つの自然な発話を作るRoleであり、candidate search engineではない。
