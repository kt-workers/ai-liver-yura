# V2 Character Language Lab Evidence Gate

Owner Validation Work: #434
Parent canonical: `character_language_lab_contracts.md`
Status: Canonical Supplement / Validation Evidence Boundary

## 1. Purpose

#434では、Character Language生成engineの「処理が完了した」という結果と、release/mergeに使える**Integrated evidence**を同一視しない。

Runtime構成は次の3段に分ける。

```text
CharacterLanguageLabService
  production/fixture composition + actual run generation
        ↓
CharacterLanguageLabGate
  Integrated / Isolation evidence classification
        ↓
Render API / UI / Export
```

`CharacterLanguageLabService`は実行engineであり、release判定Authorityではない。
`CharacterLanguageLabGate`を通っていないrunをIntegrated evidenceとして扱わない。

---

## 2. Isolation rule

Isolation Modeは常に:

- `evidence_class = isolation_only`
- `integrated_machine_gate_passed = false`
- `integrated_evidence_eligible = false`

とする。

Provider callや#363を実行して成功してもIntegratedへ昇格しない。

---

## 3. Integrated machine gate

Integrated machine gateには最低限次を全て要求する。

1. #354 production Character Definition sourceが利用可能
2. #355 production projection成功
3. #362 production Plan commit成功
4. #330 production Character Language commit成功
5. #363 semantic verificationが有効
6. 全actual CharacterUtteranceが#363 `ACCEPTED`

#363を無効化したIntegrated runは:

```text
integrated_machine_gate_passed = false
integrated_evidence_eligible = false
gate_blocker = SEMANTIC_VERIFICATION_REQUIRED
```

#363が正常実行されてもactual utteranceが`REJECTED`なら:

```text
integrated_machine_gate_passed = false
integrated_evidence_eligible = false
gate_blocker = SEMANTIC_ACCEPTANCE_REQUIRED
```

VerifierのProvider呼出成功とSemantic Acceptanceを混同しない。

---

## 4. Human gate

全actual utteranceが#363 `ACCEPTED`でも、それだけでは#434 PASSではない。

machine gate PASS後:

```text
evidence_class = integrated_pending_human
integrated_machine_gate_passed = true
integrated_evidence_eligible = false
gate_blocker = HUMAN_CHARACTER_EVALUATION_REQUIRED
```

を維持する。

Humanは`character_language_lab_contracts.md`で定義した以下を独立評価する。

- naturalness
- Yura fidelity
- natural self / restraint
- variation
- context adaptation

Human評価を#363判定へ入力しない。
#363 ACCEPTEDをHuman PASSへ自動変換しない。

---

## 5. UI constraint

Integrated Mode選択時はUIで#363 semantic verificationを必須ONとし、利用者がOFFにできないようにする。

APIを直接呼んでOFF指定された場合もserver-side evidence gateでfail-closedする。
UI制約だけをsecurity/authority boundaryにしない。

#354 production Character Definitionが未準備ならIntegrated Generateを無効化し、Isolationのみ利用可能とする。

---

## 6. Export

JSON Exportには最低限:

- `evidence_class`
- `integrated_machine_gate_passed`
- `integrated_evidence_eligible`
- `gate_blocker`
- Human ratings / notes
- `human_evaluation_complete`
- #363 result
- production provenance

を含める。

Human rating入力完了をもって自動的に`integrated_evidence_eligible=true`へ書き換えない。
最終PASSはHuman判断とGitHub Verification evidence reviewで確定する。

---

## 7. Required regression

- Isolation成功でもIntegrated昇格なし
- Integratedで#363 OFFならmachine gate FAIL
- #363 Provider正常完了 + Semantic `REJECTED`でもmachine gate FAIL
- 全actual utteranceが`ACCEPTED`ならmachine gate PASS
- machine gate PASS後もHuman評価前はIntegrated evidence未確定
- readiness取得時点でIntegrated evidence PASSを主張しない
