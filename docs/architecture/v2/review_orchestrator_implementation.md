# GitHub Review Orchestrator / Gemini Reviewer Implementation Design

Status: Canonical implementation design for Issue #371  
Parent: #369  
Depends on: #370  
Canonical contract: `docs/architecture/v2/independent_ai_review_architecture.md`  
Area: Development Tooling  
Effective: 2026-08-13

## 1. 目的

Issue #370で確定したIndependent AI Review ContractをGitHub Pull Request上で実行可能にする。

MVPではGitHub ActionsをOrchestrator runtimeとし、最初のReviewer BackendとしてGemini APIを接続する。

完成形は次とする。

```text
GitHub pull_request event
        |
        v
Independent AI Review Action
        |
        +--> Trusted Event / ReviewTarget Builder
        |       - repository / PR number
        |       - base/head ref + SHA
        |       - configured reviewer identity
        |
        +--> GitHub Context Collector (REST, read only)
        |       - PR metadata / diff / changed files
        |       - linked Issue
        |       - canonical docs
        |       - gate evidence
        |
        +--> GeminiReviewerBackend
        |       - PR content is untrusted DATA
        |       - Pydantic / JSON Schema Structured Output
        |       - ProviderReviewCandidate only
        |
        +--> Deterministic Review Validator
        |       - refetch current head
        |       - identity/session separation
        |       - verdict/finding consistency
        |       - stale SHA reject
        |       - evidence provenance validation
        |
        +--> Trusted ReviewDecision
        |
        +--> PR Review COMMENT + Actions job result
                PASS                -> exit 0
                CHANGES_REQUESTED   -> exit non-zero
                BLOCKED             -> exit non-zero
```

Reviewer Backend自身はPRのapprove / merge / branch updateを行わない。

## 2. GitHub Actions Event Policy

### 2.1 Trigger

MVPでは`pull_request`を利用する。

対象activity:

- `opened`
- `ready_for_review`
- `synchronize`
- `reopened`

Draft PRはreviewを開始しない。`opened`時にdraftなら安全に終了し、`ready_for_review`で開始する。

V2対象は次の両方を満たすPRに限定する。

- base branch = `rebuild/v2-foundation`
- PR labelに`v2`がある

### 2.2 Fork policy

fork由来PRではGitHub Actions secretsが利用できず、`GITHUB_TOKEN`も制限されるため、Gemini APIを起動しない。

```text
head repository != base repository
→ reviewer secretを要求しない
→ independent review jobはBLOCKED相当で終了
→ unsafeなpull_request_target + PR head executionへ切り替えない
```

V2の通常開発はsame-repository branchを正規経路とする。

### 2.3 Secret-bearing jobのcheckout policy

Reviewer jobはPR head / merge refをcheckoutして実行しない。

実行するReviewer実装はtrusted base SHAからcheckoutする。

```yaml
ref: ${{ github.event.pull_request.base.sha }}
```

PR headの内容はGitHub REST APIからdiff / file contentとして取得し、実行せずDATAとして扱う。

注意:
- #371をmergeするまでbase branchにreviewer script/workflowが存在しないため、#371自身は新reviewer workflowのE2E対象にできない。
- これはbootstrap制約であり、#371 merge後の通常PRへは適用しない。

## 3. GitHub Token Permissions

MVP jobはleast privilegeとする。

```yaml
permissions:
  contents: read
  pull-requests: write
  issues: read
  actions: read
  checks: read
```

用途:

- `contents: read`: trusted base canonical / repository metadata取得
- `pull-requests: write`: PR Review COMMENT投稿
- `issues: read`: linked Issue取得
- `actions: read` / `checks: read`: GateEvidence取得

branch / contents writeは付与しない。

Custom Check RunをRESTで生成する設計にはしない。Actions job自体がGitHub Checkとして残るため、#373でこのjobをRequired Check化する。

## 4. GitHub Persistence Policy

### 4.1 PR review

MVPではReview APIの`COMMENT` eventを使用する。

理由:

- `APPROVE`をGitHub Actionsへ許可するrepository settingに依存しない
- ReviewerのPASSとGitHub human approvalを混同しない
- `REQUEST_CHANGES`権限/運用差をMerge Gate Authorityにしない
- merge eligibilityはActions job conclusionで機械判定できる

Review bodyにはmachine-readable markerを含める。

```text
<!-- yura-independent-ai-review:v1 -->
Decision: PASS | CHANGES_REQUESTED | BLOCKED
Reviewed-Head-SHA: ...
Reviewer-Agent: ...
Reviewer-Session: ...
Provider: gemini
Model: ...
Cycle-Key: ...

Findings...
```

### 4.2 Job conclusion

- PASS: process exit code 0
- CHANGES_REQUESTED: reviewを投稿後exit code 2
- BLOCKED: reviewを投稿後exit code 3
- infrastructure/internal error: exit code 4

GitHub Actions上はいずれも0以外はfailureとなる。詳細decisionはreview body / audit JSONで区別する。

## 5. Reviewer Identity

MVP configured identity:

```text
role = REVIEWER
provider = google-gemini
model = GEMINI_REVIEW_MODEL
agent_id = yura-independent-reviewer-gemini
session_id = <workflow run id>:<run attempt>:<PR head SHA>
principal = github-actions[bot]
credential_scope = REVIEW_WRITE
```

Implementer identityはPR metadata / known implementation provenanceから構築する。

MVPでは最低限:

```text
agent_id = PR author / implementation metadataから導出
session_id = PR head lineage metadataが取得できる場合に使用
```

独立性を証明する情報が不足する場合、推測でPASSにせずBLOCKEDにする。

#372でImplementer Workerが導入された後は、Implementer identityを明示metadataとしてPRへ永続化する。

## 6. Review Context Collection

### 6.1 Trusted sources

GitHub RESTから取得する。

- current PR metadata
- target base/head SHA
- diff
- changed file list
- linked Issue
- Issueが参照するcanonical design
- current workflow/check evidence

PR本文に記載されたテスト結果は参考PR_DATAであり、GateEvidenceにはしない。

### 6.2 Linked Issue resolution

MVPはPR bodyから次を抽出する。

- `Relates to #N`
- `Closes #N` / `Fixes #N` / `Resolves #N`

候補IssueをGitHub APIから取得し、`v2` labelと責務を確認する。

Work Issueを一意に特定できない場合はBLOCKED。

### 6.3 Canonical resolution

Issue本文の`Canonical:` sectionからrepository pathを抽出する。

canonical pathはbase SHAから取得する。

PR自身がcanonicalを変更している場合:

- base canonical = CANONICAL_REQUIREMENT
- PRで変更されたcanonical = PR_DATA / proposed change

PR側の変更文書をReviewer policyのAuthorityとして使用しない。

### 6.4 Diff limits

巨大PRを無制限に一回のpromptへ入れない。

MVP policy:

- diff byte/token budgetを設定可能にする
- budget超過時に内容を黙って切り捨ててPASSしない
- chunk reviewまたはBLOCKEDへ遷移する

初期実装では安全側としてbudget超過をBLOCKEDにしてよい。chunked aggregationは後続拡張可能。

## 7. GateEvidence

MVPで収集するevidence:

- GitHub Actions workflow runs / jobs
- commit status / checks when取得可能

required gate nameはconfiguration化する。

初期値は空配列を許可し、#373でV2 Merge Gate required check setを確定する。

ただし取得したevidenceは必ずtarget head SHAと結びつける。

別SHAの成功結果をcurrent PASS根拠にしない。

## 8. Gemini Reviewer Backend

### 8.1 SDK

CI専用dependencyとして`google-genai`を利用する。

製品runtimeの`requirements.txt`へGemini SDKを追加しない。

専用file:

`tools/independent_review/requirements.txt`

を使用する。

### 8.2 Model

modelはGitHub Actions repository variable `GEMINI_REVIEW_MODEL`で上書き可能にする。

default:

`gemini-3.6-flash`

model名をDomain Contractへ埋め込まない。

### 8.3 Secret

Repository Actions secret:

`GEMINI_API_KEY`

secret不存在はBLOCKED。ログ、review body、auditへ値を出さない。

### 8.4 Structured Output

Pydantic schemaからJSON Schemaを生成し、Gemini Structured Outputへ渡す。

Provider output schema:

```text
ProviderReviewCandidate
- verdict_candidate
- findings[]
- summary
- confidence?
- echoed_head_sha?
```

Provider responseは`model_validate_json()`後もtrustedではない。

Deterministic Validatorを通過した後だけ`ReviewDecision`へ昇格する。

### 8.5 Prompt construction

promptは明示セクションに分割する。

```text
[SYSTEM REVIEW POLICY]
固定Reviewer policy

[AUTHORITY: ISSUE_SCOPE]
...

[AUTHORITY: CANONICAL_REQUIREMENT]
...

[UNTRUSTED: PR_METADATA]
...

[UNTRUSTED: PR_DIFF]
...

[TRUSTED FACTS: GATE_EVIDENCE]
...
```

`PR_DIFF`内のinstructionをsystem instructionとして扱わないことをReviewer policyに明示する。

## 9. Python Module Layout

```text
tools/independent_review/
├── __init__.py
├── requirements.txt
├── models.py
├── github_client.py
├── context_builder.py
├── reviewer_backend.py
├── gemini_backend.py
├── validator.py
├── persistence.py
└── main.py

tests/tools/independent_review/
├── test_models.py
├── test_context_builder.py
├── test_validator.py
├── test_persistence.py
└── test_main.py

.github/workflows/
└── independent-ai-review.yml
```

Network/API部分はPort的に分離し、unit testではFake GitHub / Fake Reviewer Backendを使う。

## 10. Deterministic Validation

MVPで必須:

- PR current headをreview完了直前に再取得
- current head == ReviewTarget.head
- reviewer agent/session != implementer agent/session
- reviewer credential scope != implementation write / orchestration
- finding ID uniqueness
- fingerprint existence
- BLOCKING finding集合とdecision consistency
- PASS + BLOCKING reject
- CHANGES_REQUESTED + BLOCKING 0 reject
- provider output schema validation
- candidate echoed SHA mismatch reject
- canonical/context欠損時PASS禁止

## 11. Idempotency / Concurrency

Actions concurrency:

```text
group = independent-ai-review-<PR number>
cancel-in-progress = true
```

new synchronize eventが来た場合、旧runをcancelする。

さらに永続化直前にcurrent headをrefetchし、old runが遅れて完了してもstale decisionをcurrent PASSとして投稿しない。

review bodyのcycle markerを利用し、同一head/cycleの重複投稿を抑止する。

## 12. Error Policy

- Gemini timeout / rate limit: bounded retry
- schema invalid: bounded retry後BLOCKED
- GitHub context取得失敗: BLOCKED
- stale SHA: stale audit + failure、old PASS投稿なし
- missing API key: BLOCKED
- unsupported fork: BLOCKED
- context budget overflow: BLOCKED（初期MVP）

内部例外stack traceやprovider raw errorをPRへそのまま出さない。

## 13. Tests

### Unit

- schema serialization
- agent/session collision
- PASS + BLOCKING reject
- CHANGES_REQUESTED without BLOCKING reject
- stale head reject
- echoed head spoof
- canonical resolution
- linked Issue ambiguity
- PR data prompt injection remains DATA
- duplicate marker detection
- secret redaction
- oversized context BLOCKED

### Adjacent / Fake E2E

Fake GitHub + Fake Reviewer:

1. ready PR
2. context build
3. PASS candidate
4. deterministic PASS
5. review COMMENT生成
6. exit 0

Failure variants:

- CHANGES_REQUESTED -> exit 2
- BLOCKED -> exit 3
- head changes during review -> stale/no PASS
- duplicate run -> no duplicate current review

### Live Verification

#371 merge後:

1. Repository secret `GEMINI_API_KEY`設定
2. optional variable `GEMINI_REVIEW_MODEL`設定（未設定ならdefault）
3. PR #368をreview eventで再起動
4. Gemini review resultを確認
5. reviewed SHAが#368 current headと一致
6. Reviewerがbranchを変更していないことを確認
7. PASS / findingsの品質を確認

実Gemini APIを使うため、この工程はVerificationとして扱う。

## 14. Bootstrap / Rollout

#371自身がreview workflowを追加するPRでは、base branchにworkflowがまだ存在しないため、その新workflowを#371自身の独立review Authorityにはできない。

#371実装PRは:

- Unit / fake adjacent test
- deterministic contract review
- #370のbootstrap lineageでの最終確認

までを行い、merge後に#368を最初のLive independent review対象とする。

#368がPASSするまで#321をmergeしない。

#371のbootstrap例外を#372以降へ一般化しない。

## 15. Done / Verification Boundary

Implementation Done条件:

- workflow / Python module / tests完成
- fake E2E PASS
- secret-bearing jobがPR head codeを実行しない
- branch write permissionなし
- Gemini backend provider-neutral contract準拠

その後Project Statusは`Verification`へ進める。

Human Verification / environment setup:

- `GEMINI_API_KEY` secret設定
- actual Gemini review of #368
- review結果 / SHA /権限境界確認

Live Verification PASS後に#371をDoneとする。
