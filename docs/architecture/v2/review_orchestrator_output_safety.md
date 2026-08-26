# Review Orchestrator Output Safety

Status: 歴史参照。出力安全化の知見は保持するが、Issue #371の現行実装Authorityではない。
Extends: `docs/architecture/v2/review_orchestrator_implementation.md`  
Parent contract: `docs/architecture/v2/independent_ai_review_architecture.md`  
Effective: 2026-08-13

> 現行#371の出力安全境界は`optional_review_support_contracts.md`に従う。本書は旧自動GitHub Review投稿案の履歴補足である。

## 1. 目的

Gemini等のReviewer Backendが返したstructured outputはschema validation後も、表示用文字列まで信頼済みになるわけではない。

悪意あるPR diffやprompt injectionから誘導されたmodel outputをGitHub PR ReviewへそのままMarkdownとして永続化せず、判定Authorityと表示安全性を分離する。

## 2. Trust Boundary

`ProviderReviewCandidate`に含まれる以下はuntrusted presentation dataとして扱う。

- summary
- finding title
- explanation
- evidence text
- file/location text
- finding identifier等のprovider由来表示値

Deterministic ValidatorがPASS/CHANGES_REQUESTED/BLOCKEDの意味整合を確認しても、上記文字列をGitHub Markdownへ無加工で昇格しない。

## 3. Persistence Sanitization

PR Review COMMENTへ永続化する直前に、model由来文字列をplain-safe Markdownへ変換する。

最低限:

- `@user` / `@team` mentionを中和し通知誘発を防ぐ
- HTML tag/comment境界をentity化する
- Markdown制御文字をescapeし、modelが任意link/image/heading等を構築しないようにする
- control characterを除去または置換する
- trusted machine marker / Reviewed-Head-SHA / Cycle-Key等はprovider文字列から生成しない

Reviewer identity、reviewed SHA、cycle key等のmachine-readable headerはOrchestratorのtrusted dataからのみ生成する。

## 4. Output Size Bounds

Providerが異常に大きなstructured outputを返した場合、GitHub Review APIへそのまま送信しない。

MVP deterministic limit:

- findings: 最大50件
- summary: 最大8,000文字
- finding title: 最大500文字
- finding explanation: 最大8,000文字
- evidence: 1 finding最大20件
- evidence item: 最大2,000文字

超過は`ReviewValidationError`として扱い、PASSへ昇格しない。

この上限はGitHub API上限ぎりぎりを狙う値ではなく、reviewを人間・Implementerが追跡可能なサイズへ保つsafety boundである。

## 5. Authority Invariant

表示サニタイズはReview verdictの意味を変更するAuthorityではない。

```text
ProviderReviewCandidate
→ schema validation
→ deterministic semantic validation
→ trusted ReviewDecision
→ presentation sanitization
→ GitHub PR Review COMMENT
```

サニタイズ前のmodel textを再解釈してverdictを変えない。

## 6. Unit Acceptance

最低限次を自動検証する。

- model summary内の`@victim`がGitHub mentionとして残らない
- HTML comment断片がそのまま残らない
- Markdown link制御文字がescapeされる
- oversized summaryがdeterministic validationでrejectされる
- machine marker / reviewed SHA / cycle keyはsanitization対象のprovider textから構築されない
