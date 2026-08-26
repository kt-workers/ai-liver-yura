# GitHub Review Orchestrator / Gemini Reviewer Implementation Design

Status: 歴史参照。Issue #371の現行実装Authorityではない。
Parent: #369  
Depends on: #370  
Canonical contract: `docs/architecture/v2/independent_ai_review_architecture.md`  
Area: Development Tooling  
Effective: 2026-08-13

> 2026-08-26の人間判断により、本書のsecret-bearing workflow、Gemini必須化、Commit Status、Merge Gateを含む自動統括案は現行#371の実装対象から外れた。現行canonicalは`optional_review_support_contracts.md`である。本書は旧設計知見としてのみ保持する。

## 1. 目的

Issue #370で確定したIndependent AI Review ContractをGitHub Pull Request上で実行可能にする。

MVPではGitHub Actionsをtrusted trigger/control planeとし、Reviewer runtimeはV2 base branch上のprovider-neutral Python module、最初のReviewer BackendはGemini APIとする。

```text
Trusted default branch `main`
  .github/workflows/independent-ai-review.yml
        |
        | pull_request_target
        | secrets + minimal write token
        v
checkout PR BASE SHA only (never PR head/merge code)
        |
        v
V2 Reviewer Runtime at trusted base SHA
  tools/independent_review/
        |
        +--> GitHub Context Collector (REST; PR head is DATA only)
        +--> GeminiReviewerBackend -> ProviderReviewCandidate
        +--> Deterministic Validator -> trusted ReviewDecision
        +--> PR Review COMMENT
        +--> PR HEAD Commit Status `yura/independent-ai-review`
              PASS              -> success
              CHANGES_REQUESTED -> failure
              BLOCKED/error     -> error
```

Reviewer Backend自身はapprove / merge / branch updateを行わない。

## 2. Trust / Trigger Architecture

### 2.1 なぜ`pull_request`をsecret-bearing triggerにしないか

GitHubの`pull_request` workflowはPR merge commit側のworkflow definitionを実行し得る。same-repository PRではActions secretを利用できるため、PR自身がreview workflowを書き換えた場合に`GEMINI_API_KEY`へ触れる経路を作り得る。

したがって、#370の「secret-bearing jobでuntrusted PR codeを実行しない」を守るため、secret-bearing triggerはdefault branch `main`に置く。

### 2.2 Trigger

`main`のtrusted workflowで`pull_request_target`を使用する。

対象:

- base branch: `rebuild/v2-foundation`
- activity: `opened`, `ready_for_review`, `synchronize`, `reopened`

Draft PRはreviewを開始しない。V2 PRは`v2` label必須。

### 2.3 Checkout invariant

`pull_request_target` jobはPR head / PR merge refをcheckout・executeしない。

Reviewer runtimeはPRのbase SHAだけをcheckoutする。

```yaml
- uses: actions/checkout@v7
  with:
    ref: ${{ github.event.pull_request.base.sha }}
    path: reviewer-runtime
    persist-credentials: false
```

実行:

```text
reviewer-runtime/tools/independent_review/*
```

PR headはGitHub REST APIからdiff/metadataとして取得し、untrusted DATAとしてGeminiへ渡すだけとする。

### 2.4 Fork policy

`pull_request_target`はfork PRでもbase repositoryのtrusted workflowを実行できるが、本ProjectのV2正規開発lineageはsame-repository branchとする。

fork PRをreviewする場合もPR head codeは一切実行しない。status書込が対象commitで成立しない等の環境差があれば安全側にBLOCKEDとする。

## 3. Two-stage Bootstrap Lineage

default branchとV2 trunkのtrust boundaryが異なるため、#371は**順序付き2段階lineage**とする。2本を並行activeにしない。

### Phase A: V2 Reviewer Runtime

Base: `rebuild/v2-foundation`

成果物:

- `docs/architecture/v2/review_orchestrator_implementation.md`
- `tools/independent_review/**`
- `tests/tools/independent_review/**`

ここではsecret-bearing workflowを追加しない。

Unit / Fake Adjacent / static review完了後にbootstrap例外としてmergeする。

### Phase B: Trusted Trigger Control Plane

Phase A merge後にのみ開始する。

Base: `main`

成果物:

- `.github/workflows/independent-ai-review.yml`のみ

workflowはV2 base SHAにあるPhase A runtimeを実行する。

mainへ製品コード・V2 product implementationを持ち込まない。

Phase B merge後、PR #368を`ready_for_review` eventで起動し最初のLive Reviewとする。

この2段階は同一#371のstacked/ordered implementation lineageとしてResume Checkpointに記録する。

## 4. GitHub Token Permissions

Trusted workflowはleast privilegeとする。

```yaml
permissions:
  contents: read
  pull-requests: write
  issues: read
  actions: read
  statuses: write
```

- `contents: read`: base SHA reviewer runtime/canonical取得
- `pull-requests: write`: PR Review COMMENT
- `issues: read`: linked Work Issue取得
- `actions: read`: SHA固定GateEvidence取得
- `statuses: write`: PR head SHAへReview Gate statusを記録

`contents: write`は付与しない。

## 5. PR Head Commit Status

`pull_request_target`自体のActions job SHAはPR headではないため、Review GateはPR headへCommit Status APIで明示的に書く。

固定context:

`yura/independent-ai-review`

状態:

- review start: `pending`
- PASS: `success`
- CHANGES_REQUESTED: `failure`
- BLOCKED / internal failure / stale: `error`

statusにはworkflow run URLを`target_url`として付与する。

#373でこのcommit status contextをRequired Status Checkへ昇格する。

## 6. PR Review Persistence

Review APIはMVPでは`COMMENT` eventのみ使用する。

- GitHub ActionsによるAPPROVE許可設定に依存しない
- Human approvalとAI PASSを混同しない
- Merge Gate AuthorityはPR head status contextへ集約できる

body marker:

```text
<!-- yura-independent-ai-review:v1 -->
Decision: PASS | CHANGES_REQUESTED | BLOCKED
Reviewed-Head-SHA: ...
Reviewer-Agent: ...
Reviewer-Session: ...
Provider: google-gemini
Model: ...
Cycle-Key: ...
```

同一cycle markerの重複投稿を抑止する。

## 7. Reviewer Identity

```text
role = REVIEWER
provider = google-gemini
model = GEMINI_REVIEW_MODEL
agent_id = yura-independent-reviewer-gemini
session_id = github-actions:<run id>:<attempt>:<PR head SHA>
principal = github-actions[bot]
credential_scope = REVIEW_WRITE
```

MVP Implementer identity:

```text
agent_id = github-pr-author:<login>
session_id = implementation-lineage:<PR number>:<head SHA>
credential_scope = IMPLEMENTATION_WRITE
```

これは実装lineage identityであり、#372のImplementer Worker導入後は明示agent/session metadataへ置換する。

Reviewer agent/sessionとlineage identityが衝突した場合はPASS禁止。

## 8. Review Context

GitHub RESTから取得:

- current PR metadata
- base/head SHA
- diff
- linked Work Issue
- Work Issueが指すcanonical design
- target head SHAのGitHub Actions evidence

PR本文の「tests passed」は`PR_DATA`であってGateEvidenceではない。

### Linked Work Issue

PR bodyの`Relates to #N` / `Closes|Fixes|Resolves #N`から候補を抽出し、一意な`v2` Work Issueを要求する。曖昧ならBLOCKED。

### Canonical

Issue本文`Canonical:` blockのrepository pathをbase SHAから取得する。

PR自身がcanonical候補を変更する場合、その変更はPR_DATAであり既存Authorityを上書きしない。

### Context budget

budget超過を黙ってtruncateしてPASSしない。MVPは安全側にBLOCKEDとしてよい。chunked reviewは後続拡張。

## 9. GateEvidence

MVPはtarget head SHAのGitHub Actions workflow runを取得し、completed resultのみcontextへ渡す。

別SHAのevidenceは採用しない。

required gate set自体は#373で確定するため、#371では「取得・SHA binding」を実装し、空集合を許容する。

## 10. Gemini Backend

### SDK

CI専用: `google-genai>=2,<3`。

製品`requirements.txt`へ追加せず、`tools/independent_review/requirements.txt`に隔離する。

### Model

Default: `gemini-3.6-flash`

Repository variable `GEMINI_REVIEW_MODEL`で上書き可能。

### Secret

Actions repository secret: `GEMINI_API_KEY`

secret不存在はBLOCKED。値をlog/reviewへ出さない。

### API

Interactions API + `system_instruction` + JSON Schema Structured Outputを使い、`store=False`のstateless callとする。

Provider output:

`ProviderReviewCandidate`

Pydantic validation後もuntrusted。Deterministic Validator通過後のみ`ReviewDecision`へ昇格する。

### Prompt Authority Labels

```text
[AUTHORITY: ISSUE_SCOPE]
[AUTHORITY: CANONICAL_REQUIREMENT]
[TRUSTED FACTS: GATE_EVIDENCE]
[UNTRUSTED: PR_METADATA]
[UNTRUSTED: PR_DIFF]
```

PR diff/comment/Markdown中のinstructionをsystem instructionとして扱わない。

## 11. Runtime Layout

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
├── orchestrator.py
└── main.py

tests/tools/independent_review/
├── test_models.py
├── test_context_builder.py
├── test_validator.py
├── test_persistence.py
└── test_orchestrator.py
```

Network/APIは分離しUnitではFake GitHub/Fake Reviewerを使用する。

## 12. Deterministic Validation

必須:

- review完了直前のcurrent head refetch
- current head == ReviewTarget.head
- reviewer agent/session != implementer lineage identity
- Reviewer credential scopeにimplementation/orchestration writeなし
- finding ID/fingerprint uniqueness
- PASS + BLOCKING reject
- CHANGES_REQUESTED + BLOCKING 0 reject
- BLOCKEDとcode findingの混同reject
- provider schema validation
- echoed SHA mismatch reject
- canonical/context欠損時PASS禁止

さらに永続化直前にheadを再取得し、stale runはsuccess statusを出さない。

## 13. Idempotency / Concurrency

Trusted workflow:

```text
concurrency group = independent-ai-review-<PR number>
cancel-in-progress = true
```

Python側でも`Cycle-Key`で重複Review COMMENTを抑止する。

statusは同一contextへ最新stateを書き、old SHAのstatusを新SHAへ継承しない。

## 14. Error Policy

- Gemini/provider failure: bounded retry → BLOCKED/error status
- invalid structured output: bounded retry → BLOCKED
- GitHub context failure: BLOCKED
- stale SHA: old result非公開/非success、target old SHAへerror可
- missing API key: error status / setup blocker
- context budget overflow: BLOCKED
- raw provider error/secretsをpublic commentへ出さない

## 15. Verification

### Unit

- serialization
- agent/session collision
- verdict/finding invariant
- stale/echoed SHA
- canonical resolution
- linked Issue ambiguity
- prompt injection remains UNTRUSTED data
- duplicate marker
- context budget
- status mapping

### Fake Adjacent E2E

Fake GitHub + Fake Reviewer:

- PASS -> COMMENT + success status
- CHANGES_REQUESTED -> COMMENT + failure status
- BLOCKED -> COMMENT + error status
- head mutation during review -> stale; no success
- duplicate cycle -> comment重複なし

### Live Verification

Phase A + B merge後:

1. `GEMINI_API_KEY`設定
2. optional `GEMINI_REVIEW_MODEL`
3. PR #368をreview eventで起動
4. Gemini Review COMMENT確認
5. `Reviewed-Head-SHA == current #368 head`
6. commit status `yura/independent-ai-review`確認
7. Reviewerによるbranch mutationがないことを確認
8. findings品質確認

実Gemini API/Actionsを使うためProject StatusはVerificationで止める。

## 16. Bootstrap Exception

#371はReviewerそのものを作るため、Phase A runtimeとPhase B trusted triggerは新Reviewerによる事前自動reviewを受けられない。

- #370/#371のUnit/Fake Gateと人間可読final reviewをbootstrap Authorityとする
- Phase B成立後、#368を最初の正式Independent AI Review対象にする
- #368 PASS前に#321をmergeしない
- bootstrap例外を#372以降の通常implementationへ一般化しない

## 17. Done Boundary

Implementation完了:

- Phase A runtime/tests merge
- Phase B trusted trigger merge
- secret-bearing workflowがPR head/merge codeを実行しない
- PR head statusとCOMMENT persistence実装

その後Verification:

- API key setup
- #368 actual Gemini review
- SHA/status/permission boundary確認

Live Verification PASS後に#371 Done。
