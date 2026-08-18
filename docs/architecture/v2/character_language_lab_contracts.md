# V2 Character Language Lab Contracts

Owner Validation Work: #434
Upstream production: #354 / #355 / #362 / #330
Downstream observer: #363
Related standalone semantic lab: #427
Status: Validation-only canonical / no production authority

## 1. Purpose

本書は、#330 production Character Language LLMが、確定済み`SpeechSemanticPlan`を**ゆら自身の自然な言葉**へ実現できるかを単独・統合検証する#434 Character Language Labの契約を定義する。

Lab自身はCharacter、What-to-say、semantic acceptanceのAuthorityを持たない。

```text
production Character Definition (#354)
             ↓
#355 production projection
             ↓
CharacterLanguageProfile ───────────────┐
                                       │
#362 production SpeechSemanticPlan ─────┼─> #330 production Character Language
                                       │
                                       ↓
                              actual CharacterUtterance
                              ├─ Human Character quality
                              └─ #363 production semantic observer
```

Character Definition/Profile → SpeechSemanticPlanという直列生成関係ではない。ProfileとPlanは異なるAuthorityから#330へ合流する。

---

## 2. Two modes

### 2.1 Integrated Mode

release / merge evidenceとして扱える唯一の#434 gate。

必須:

1. production Character Definition source
2. #355 production strict loader / projector
3. `CharacterLanguageProfile`
4. #362 production contractを通してcommitされた`SpeechSemanticPlan`
5. #330 production `CharacterLanguageRealizer`
6. #330 production instructions / strict output schema / OpenAI Role config helper
7. actual Provider resultからcommitされた`CharacterUtterance`
8. Human Character quality evaluation
9. 同じactual `CharacterUtterance`を#363 production verifierへ投入
10. 全段階のidentity / provenance / revision / model policy / timingを同一runへ記録

Integrated ModeではLab-owned Profile / Plan / Prompt / schema / provider formatを使用してはならない。

### 2.2 Isolation Mode

原因切り分け専用。

許可例:

- fixed Profile + fixed Planで#330だけ反復
- fixed PlanでProfile facet差比較
- fixed Profile/Planでmodel / reasoning差比較
- variation 5〜10回比較
- #363 rejection reproduction
- malformed Provider output / schema failureの診断

Isolation fixtureは明示的に`isolation`とlabelし、Integrated PASSへ昇格させない。

---

## 3. Current upstream gate — #354

2026-08-19 GitHub liveでは#355 loader/projectorはproductionに存在するが、#354 Character DefinitionはHuman Verification中である。

#355 canonicalはproduction sourceを次のように定める。

```text
character_definitions/v2/<character_id>.yaml
```

このcontentは#354 ownershipであり、#434は生成・補完・推測しない。

そのためproduction `yura.yaml`が存在しない間:

- Integrated Modeは`BLOCKED_UPSTREAM_CHARACTER_DEFINITION`
- Integrated run endpointはfail closed
- hand-built Profileへfallbackしない
- Isolation Modeだけを利用可能にできる
- UI / ExportはIntegrated未実行を明示する

#354を#434都合で急いでmergeしてはならない。Human-confirmed contentがAuthorityである。

---

## 4. Production reuse boundary

#434はproduction assetをimportして使用する。

### Character projection

- `load_character_definition_yaml()`
- #355 Character Definition contracts
- `project_character_definition()`で`CharacterProjectionBundle`を生成し、その`.language`を使用

### Speech Semantics

- `SpeechSemanticsPlanner`
- `SpeechSemanticAuthority`
- production `SpeechSemanticPlan` contracts

Integrated ModeではPlan objectをLabが直接constructorで作成して完了扱いしない。
Production planner / authority commit pathを通す。

### Character Language

- `CharacterLanguageRealizer`
- `CharacterLanguageAuthority`
- `character_language_instructions()`
- `character_language_output_schema()`
- `character_language_openai_role_config()`
- provider format `character_language_candidate_v1`

### Semantic Verification

#363 production contracts / schemas / verifierを利用する。
#427 standalone LabのUIやfixtureを#434のAuthorityへしない。

---

## 5. Human Character quality axes

Humanは#363とは別にCharacter qualityを評価する。

### A. Naturalness

- 日本語として自然
- 会話として硬すぎない
- AI assistant / 説明書調へ寄らない
- 不自然な定型導入 / 締めへ収束しない
- 過度な修辞や語尾癖だけにCharacter性を依存しない

### B. Yura fidelity

confirmed `CharacterLanguageProfile`に対する:

- 距離感
- 柔らかさ
- directness
- rhythm
- verbosity
- humor / teasing
- hesitation
- 親しみやすさ

### C. Natural self / restraint

- Characterを演じている感を過剰に出さない
- 毎回全facetを盛らない
- neutral speechも自然
- Situationに不要な冗談 / 照れ / 質問 / 自己開示を追加しない
- ProfileをFact sourceにしない

### D. Variation

同じPlan / Profile / constraints / model policyで5〜10回程度生成し:

- 語彙
- 語順
- rhythm
- phrase segmentation

に自然なvariationがあることを確認する。
Semantic meaningは維持する。
固定template slot置換や毎回同じ冒頭 / 語尾 / 口癖への収束はNG。

### E. Context adaptation

最低限:

- neutral fact
- unknown / uncertainty
- negation
- gratitude
- apology
- self-disclosure allowed / forbidden
- degree
- execution status
- acknowledgement / answer等discourse差
- relationship constraint差
- question / new-direction budget差

### F. Model / reasoning comparison

比較項目:

- Human quality
- schema stability
- semantic acceptance rate
- latency
- input/output token usage

可能ならmodel表示を隠したblind pairwise Human比較を利用する。

---

## 6. Human vs #363 responsibility

同一actual outputを二方向で評価する。

```text
actual CharacterUtterance
  ├─ Human: ゆらとして自然か
  └─ #363: SpeechSemanticPlanの意味を保持したか
```

Human評価結果を#363のsemantic判定へ入力しない。
#363のPASS/FAILをHuman Character fidelity判定へ自動変換しない。

例:

- Human PASS / #363 FAIL: 自然だが意味を壊した
- Human FAIL / #363 PASS: 意味は正しいがCharacter品質が低い
- Human PASS / #363 PASS: 両軸PASS候補

---

## 7. Run identity / provenance

1 runは最低限次を記録する。

### Run

- run_id
- mode: `integrated | isolation`
- scenario_id
- repetition_index
- started_at / completed_at
- status

### Character source

- character_id
- Character Definition source path
- schema_version
- definition_revision
- source content hash / revision identity
- projected CharacterLanguageProfile
- profile projection status

### Speech plan

- plan_id
- source decision / intent / event IDs
- revision vector
- proposition list
- self-disclosure policy
- question/new-direction budget
- production commit status

### Character Language

- request_id / trace_id
- #330 Role / input / output schema IDs
- provider format name
- model class
- provider model
- reasoning effort
- latency
- token usage
- raw structured candidate
- committed CharacterUtterance

### Semantic Verification

- #363 request / trace identity
- Role A / Role B model policy
- acceptance status
- rejection reasons
- material unit accounting
- relation edges
- latency / token usage

### Human evaluation

- axis ratings / pass-fail
- free note
- pairwise blind selection metadata when used

Provenanceが欠落したrunはIntegrated evidenceに使用しない。

---

## 8. Status model

Labは最低限次を区別する。

- `READY`
- `BLOCKED_UPSTREAM_CHARACTER_DEFINITION`
- `INVALID_INPUT`
- `PROVIDER_FAILED`
- `CHARACTER_COMMIT_REJECTED`
- `SEMANTIC_VERIFICATION_FAILED`
- `COMPLETED`

Isolation成功をIntegrated `COMPLETED`として記録しない。

---

## 9. Fail-closed rules

- production Character Definition unavailable -> Integrated拒否
- Character Definition loader failure -> Integrated拒否
- no confirmed CharacterLanguageProfile facet -> source状態を表示し、fixture fallback禁止
- SpeechSemanticPlan production commit failure -> #330を呼ばない
- #330 provider error / schema invalid -> no CharacterUtterance commit
- #330 identity / freshness / constraint mismatch -> no run PASS
- #363 unavailable / invalid response -> semantic axis未評価としてIntegrated PASS禁止
- missing provenance -> Integrated PASS禁止
- generic fixed Character phrase fallback禁止
- raw user text / raw Emotion / Desire / Drive / Activity / Execution payloadを#330へ追加禁止
- TTS / Bodyを本Labへ混ぜない

---

## 10. UI / workflow

### Integrated panel

- upstream readiness summary
- Character Definition source / revision
- projected Profile read-only view
- production SpeechSemanticPlan read-only view
- model / reasoning selection
- Generate
- actual CharacterUtterance
- Human evaluation controls
- #363 semantic result
- provenance / timing / token metrics
- Export

Production sourceが未準備ならGenerateを無効化し、blockerを具体表示する。

### Isolation panel

- fixture Profile / Plan選択・編集
- repetition count 1〜10
- model / reasoning selection
- #330 generation results
- optional #363 diagnosis
- `ISOLATION ONLY`表示

### Comparison

- repeated variants side-by-side
- repeated opening/ending phraseの観察補助
- pairwise Human選択
- latency / tokens / schema success / semantic acceptance集計

自動Character quality scoreをAuthorityにしない。

---

## 11. Export contract

Exportは1つのJSONまたはMarkdown packageで、最低限次を含む。

- Lab version
- git branch / exact head
- run mode / scenario
- all production provenance
- Profile / Plan / actual CharacterUtterance
- Human evaluation
- #363 semantic verification
- model/reasoning policy
- latency / usage
- blocker / failure information

Secret / API key / provider raw exception secretは含めない。

---

## 12. Required automated tests

### Readiness

- production Character Definition missing -> Integrated blocked
- malformed Character Definition -> blocked / no fixture fallback
- Isolation fixtureはIntegrated statusへ昇格しない

### Production reuse

- #330 production instructions objectを使用
- #330 production output schema objectを使用
- #330 production provider format/config helperを使用
- #355 production loader/projectorを使用
- #362 production commit pathを使用
- #363 production verifier/contractsを使用

### Generation

- valid provider candidate -> actual CharacterUtterance commit
- provider timeout/error -> fail closed
- schema invalid -> no commit
- provenance mismatch -> no commit
- repeated run IDs / candidate IDsは独立

### Export

- input/output/provenance/revisions/model/timing/usageを保持
- Isolation label保持
- secret非出力

### UI/API

- Integrated blocked状態を取得可能
- repetition count上限10
- invalid model/reasoning mapping拒否
- Human evaluationがsemantic acceptanceを上書きしない

---

## 13. Verification sequence

1. deterministic CI / tests
2. current-head review
3. #354 production Character Definition/YAML readiness確認
4. Integrated smoke run
5. representative context matrix
6. same-case 5〜10 variation run
7. model/reasoning comparison
8. Human evaluation
9. same actual utteranceの#363 evaluation
10. evidence export review
11. #330 / #363 / #434へ同一run evidenceを記録

#354未準備の間は1〜2およびIsolation診断まで可能だが、3以降のIntegrated GateをPASSにしない。

---

## 14. Merge gate

#434 PASSには最低限:

- production Definition → #355 Profile provenance PASS
- production #362 Plan commit provenance PASS
- production #330 LLM actual output PASS
- Human quality matrix PASS
- natural variation evidence PASS
- model/reasoning policy evidence
- current #363 semantic preservation evidence PASS
- latency/non-blocking assessment
- exact-head deterministic CI SUCCESS
- current-head review blocking finding 0
- Integrated Exportのprovenance complete

Isolation-only evidenceではMerge Gateを閉じない。
