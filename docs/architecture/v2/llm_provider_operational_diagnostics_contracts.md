# V2 LLM Provider Operational Diagnostics Contracts

Owner Issue: #437
Parent: #356
Upstream: #357 / #323
Related: #330 / #363 / #352 / #434 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

本書は、`LLMFailureCode.PROVIDER_UNAVAILABLE`等のDomain向けfailure contractを維持したまま、Provider Adapter内部で観測したHTTP/transport/timeout/rate-limit等の**運用原因を安全なclosed diagnosticとして分離・観測する契約**を定義する。

```text
Provider SDK / HTTP failure
        ↓
#357 Provider Adapter
        ├─ Domain-facing: LLMRoleFailure
        │      coarse semantic/runtime failure contract
        │
        └─ Infrastructure observability:
               LLMProviderOperationalDiagnostic
               safe closed cause / request correlation
```

運用診断はDomain semantic Authorityではない。

---

## 2. Authority boundary

### Domain keeps

`LLMRoleFailure`はRole callerが必要とするclosed failureだけを保持する。

例:
- `PROVIDER_UNAVAILABLE`
- `PROVIDER_ERROR`
- `SCHEMA_INVALID`
- `POLICY_VIOLATION`
- `CANCELLED`

Domainへ次を追加しない。

- raw HTTP response
- provider error object
- provider-specific exception class
- response body
- Authorization/API key
- rate-limit header dump
- billing detail

### Infrastructure diagnostics owns

Provider Adapter / observability layerは、運用判断に必要なsafe categoryとcorrelation metadataを保持できる。

このdiagnosticはCharacter Language、Semantic Verification、Executive等のDomain判断入力にしない。

---

## 3. Diagnostic contract

```text
LLMProviderOperationalDiagnostic
- diagnostic_id
- logical_request_id
- role_id
- provider_id
- model_id?
- category
- http_status?
- provider_request_id?
- attempt_number
- retryable
- occurred_at
- sanitized_detail_code?
```

Rules:
- `logical_request_id`はFoundation/Role requestのcorrelation ID。
- `provider_request_id`はProviderが安全なrequest correlation IDを提供する場合だけ保持。
- `model_id`はsecretではないprovider model identityに限定し、credential/account identityは含めない。
- `sanitized_detail_code`は事前定義closed enum/string codeだけ。raw exception textを入れない。
- raw headers/body/stack traceをこのDTOへ入れない。

---

## 4. Closed failure categories

Initial categories:

```text
RATE_LIMITED_TRANSIENT
QUOTA_OR_BILLING_EXHAUSTED
REQUEST_TIMEOUT
TRANSPORT_UNAVAILABLE
PROVIDER_SERVER_ERROR
PROVIDER_REQUEST_REJECTED
AUTHENTICATION_OR_PERMISSION_FAILED
PROVIDER_PROTOCOL_ERROR
CANCELLED
UNKNOWN_PROVIDER_FAILURE
```

Categoryは運用診断であり、Domainのsemantic failure codeを置き換えない。

---

## 5. Mapping policy

### SDK/API timeout

```text
SDK timeout or client-side request deadline
→ REQUEST_TIMEOUT
→ Domain: PROVIDER_UNAVAILABLE
→ retryable: true only if request deadline/retry budget permits
```

Application-level `asyncio.wait_for` deadline超過も同様だが、既にglobal deadlineを超えている場合は再試行しない。

### Connection / transport error

```text
connection failure / DNS / TLS / transient transport
→ TRANSPORT_UNAVAILABLE
→ Domain: PROVIDER_UNAVAILABLE
→ retryable: true within bounded retry policy
```

credential errorをtransportへ誤分類しない。

### HTTP 408

```text
408
→ REQUEST_TIMEOUT
→ Domain: PROVIDER_UNAVAILABLE
→ retryable: true within deadline/retry budget
```

### HTTP 429

429を一律retryableにしない。

Provider Adapterがsafe provider code/classificationから一時rate limitを識別できる場合:

```text
429 + transient rate-limit classification
→ RATE_LIMITED_TRANSIENT
→ Domain: PROVIDER_UNAVAILABLE
→ retryable: true with bounded backoff
```

quota / billing / account capacity等、同一requestの即時retryで解消しない原因を識別できる場合:

```text
429 + quota/billing exhaustion classification
→ QUOTA_OR_BILLING_EXHAUSTED
→ Domain: PROVIDER_UNAVAILABLE
→ retryable: false
```

429だが安全に原因区別できない場合は、request-level immediate retryを無制限に行わない。初期policyではfail-closedに`retryable=false`とし、dependency-level lifecycle/backoff/recoveryへ委ねる。

Provider-specific raw error codeはAdapter内部のmapping tableだけで使用し、Domain/Exportへ露出しない。

### HTTP 5xx

```text
500..599
→ PROVIDER_SERVER_ERROR
→ Domain: PROVIDER_UNAVAILABLE
→ retryable: true within bounded retry/deadline
```

### 4xx permanent request

認証/権限:

```text
401/403 or equivalent provider classification
→ AUTHENTICATION_OR_PERMISSION_FAILED
→ Domain: PROVIDER_ERROR
→ retryable: false
```

unsupported parameter / malformed provider request等:

```text
permanent provider request rejection
→ PROVIDER_REQUEST_REJECTED
→ Domain: PROVIDER_ERROR or POLICY_VIOLATION according owning #357 mapping
→ retryable: false
```

### Response/protocol anomaly

Provider SDKが成功形を返したがAdapter contractとして解釈不能等:

```text
→ PROVIDER_PROTOCOL_ERROR
→ Domain: PROVIDER_ERROR
→ retryable: false by default
```

Structured JSON/schema mismatchは既存Domain `SCHEMA_INVALID`を使い、provider operational failureと混同しない。

---

## 6. Retry truth

`retryable`は実原因分類と現在のrequest budgetの両方を満たす場合だけtrue。

必要条件:
- categoryがtransient retry eligible
- request retry policyが許可
- attempt上限未満
- absolute deadline未超過
- cancellation未発生
- Runtime shutdown開始前

`retryable=true`は「必ずretryする」という意味ではない。

#322/#350のqueue/backpressure/lifecycle policyが最終的な再試行/admissionを調停する。

---

## 7. Safe request correlation

許可:
- logical request ID
- role ID
- attempt number
- provider request ID（取得できる場合）
- HTTP status integer
- safe category
- model ID
- timing

禁止:
- API key
- Authorization header
- full request body
- Prompt / system instruction本文
- raw user text
- raw provider response body
- arbitrary SDK exception string
- account/billing identifiers

Provider request IDはsecretではないcorrelation identifierとして扱うが、公開範囲はdiagnostics/admin/validationへ限定し、Character prompt等へ入れない。

---

## 8. Rate-limit headers

Initial V2では`remaining/reset/limit`等のraw Provider header群をcanonical diagnostic DTOへ含めない。

理由:
- providerごとにsemanticsが異なる
- header値の全面公開は不要
- retry/backoffに必要ならAdapter内部で利用できる

将来、安全でprovider-neutralなnormalized rate-limit snapshotが必要になった場合は別schema revisionで追加する。

---

## 9. Observability channel

Diagnostic publicationはbest-effort observability side-channelであり、Domain result deliveryをblockしてはならない。

```text
LLMRoleResult
→ owning Domain

LLMProviderOperationalDiagnostic
→ metrics / admin diagnostics / validation export-safe view
```

Diagnostic sink failureでProvider call結果を別failureへ変えない。

high-volume repeated同一failureはfingerprint/category単位でrate limit/coalesce可能。

---

## 10. Validation Lab exposure

#352/#434等が運用原因を表示する場合、safe diagnostic projectionだけを使う。

表示可能例:
- category
- http status
- retryable
- attempt number
- role/model
- provider request ID（必要なdiagnostic modeのみ）

表示禁止:
- raw exception
- response body
- Prompt
- credential

Human Character quality評価とProvider operational failureを同じscoreへ混ぜない。

---

## 11. Failure examples

### transient 429

```text
Domain:
  code = PROVIDER_UNAVAILABLE
  retryable = true

Diagnostic:
  category = RATE_LIMITED_TRANSIENT
  http_status = 429
```

### quota 429

```text
Domain:
  code = PROVIDER_UNAVAILABLE
  retryable = false

Diagnostic:
  category = QUOTA_OR_BILLING_EXHAUSTED
  http_status = 429
```

### 503

```text
Domain:
  code = PROVIDER_UNAVAILABLE
  retryable = true

Diagnostic:
  category = PROVIDER_SERVER_ERROR
  http_status = 503
```

---

## 12. Required tests

- SDK connection error → transport unavailable
- SDK timeout → request timeout
- HTTP 408 mapping
- transient HTTP 429 mapping / bounded retry
- quota/billing-like HTTP 429 mapping / no immediate retry
- unclassified 429 fail-closed retry policy
- HTTP 5xx mapping
- auth/permission permanent mapping
- permanent request rejection
- provider request ID safe propagation
- attempt count correctness
- deadline/cancel/shutdown overrides retryability
- raw exception/body/header/credential non-leakage
- observability sink failure does not alter Domain result
- repeated failure diagnostic coalescing/rate-limit

---

## 13. #445 Design Gate

This document completes #437's Design scope.

Production Adapter implementation remains frozen until #445 D1-D9 and final user confirmation PASS.
