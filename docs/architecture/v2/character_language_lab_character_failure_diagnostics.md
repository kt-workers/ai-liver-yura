# V2 Character Language Lab — Character Failure Diagnostics

Owner Validation Work: #434
Related Product Work: #330
Related Observer: #363
Parent canonical: `character_language_lab_evidence_gate.md`
Status: Canonical Supplement / Validation Observability

## 1. Purpose

#434 Labでは、Character Language実行失敗を一律に`CHARACTER_COMMIT_REJECTED`へ潰してはならない。

2026-08-19のweak repetition-awareness live rerunでは、10/10 runで:

- Character provider metric `status = failed`
- token usage `0 / 0`
- Lab run status `CHARACTER_COMMIT_REJECTED`
- `error_type = ValueError`
- #363未実行

となったが、Exportが`LLMRoleResult.failure`を捨てていたため、次のfailure classを区別できなかった。

- `SCHEMA_INVALID`
- `PROVIDER_ERROR`
- `PROVIDER_UNAVAILABLE`
- その他のtyped `LLMFailureCode`

この不足を解消し、Provider failureとDomain/Authority commit rejectionを分離して診断できるようにする。

---

## 2. Authority boundary

本契約は#434 Labのobservabilityだけを追加する。

変更してはならないもの:

- #330 Character Language Role / Domain Authority
- #330 fail-closed policy
- OpenAI Adapterのfailure classification
- #363 semantic policy
- production retry policy
- production semantic repair policy (#348 ownership)

Labはfailureを成功へ変換しない。
LabはProvider errorをCharacter semantic defectへ変換しない。

---

## 3. Failure classes

### 3.1 Provider / Role result failure

`LLMRolePort.invoke()`が正常に`LLMRoleResult`を返したが、result statusが`FAILED`または`TIMED_OUT`等で成功候補を持たない場合。

Labは最低限次をExportできる。

- `provider_result_status`
- `failure_code`
- `failure_message`
- `retryable`
- `attempt_count`
- `latency_ms`
- `token_usage`

`failure_code`はproduction `LLMFailureCode`のclosed valueのみ。

`failure_message`はproduction `LLMRoleFailure`が持つDomain-safe固定messageのみを使用し、最大500文字に制限する。

### 3.2 Character candidate / commit rejection

Provider resultが`SUCCEEDED`でoutputも存在した後、次のDomain validation / Authority gateで拒否された場合。

例:

- candidate schema / parser validation
- request/result identity mismatch
- provenance mismatch
- stale/live grounding mismatch
- CharacterLanguageAuthority commit rejection

この場合はProvider failureとして表示しない。

Export:

- `error_type`
- `error_message`（Domain-safe ValueErrorのみ最大500文字）
- `provider_result_status = succeeded`

### 3.3 Unknown exception

未知例外は:

- `error_type`

だけをExportし、raw exception messageを公開しない。

---

## 4. Lab status mapping

Lab UI/APIでは可能な範囲で次を区別する。

```text
Provider/Role result failed
  -> PROVIDER_FAILED

Provider succeeded + Domain candidate/commit rejected
  -> CHARACTER_COMMIT_REJECTED
```

`PROVIDER_FAILED`を#330 Character semantic quality failureとして扱わない。
`CHARACTER_COMMIT_REJECTED`も#363 semantic rejectionとは別物である。

#363はCharacterUtteranceがcommitされた後だけ実行する。

---

## 5. Secret / provider payload boundary

Exportしてはならない:

- API key
- Authorization header
- HTTP headers
- raw SDK exception body
- raw provider request/response object
- credential
- environment secret
- stack trace

Provider model name / model class / reasoning policy / closed failure code / fixed Domain-safe messageは既存provenanceとしてExport可能。

---

## 6. Diagnostic workflow

Character Provider failureを検出したら、品質characterizationを続行しない。

次の順序にする。

1. failure diagnostics対応版Labをdeploy
2. repetitions=1で同条件を実行
3. `failure_code`を確認
4. failure class別に原因を切り分ける
5. Provider/contract pathが正常化してからrepetitions=10のquality characterizationへ戻る

同じ未知failureを10回連続実行してtoken/latencyを消費しない。

---

## 7. Required regressions

- failed `LLMRoleResult`の`failure.code/message/retryable`をsafeにExportできる
- failed Provider resultは`PROVIDER_FAILED`として区別できる
- Provider `SUCCEEDED`後のDomain `ValueError`は`CHARACTER_COMMIT_REJECTED`になる
- unknown exception raw messageをExportしない
- secret / API key / header / raw SDK bodyをExportしない
- Provider failure時は#363を呼ばない
- existing successful run / strict same-Plan prior chainを壊さない
- production #330 / #363 codeを変更しない
