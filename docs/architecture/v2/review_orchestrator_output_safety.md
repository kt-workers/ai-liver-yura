# Review Orchestrator Output Safety

Status: Canonical amendment for Issue #371  
Extends: `docs/architecture/v2/review_orchestrator_implementation.md`  
Parent contract: `docs/architecture/v2/independent_ai_review_architecture.md`  
Effective: 2026-08-13

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
- Provider候補内の全文字列合計: 最大12,000文字
- 無害化・整形後のレビュー本文: 最大60,000文字

超過は`ReviewValidationError`として扱い、PASSへ昇格しない。

この上限はGitHub API上限ぎりぎりを狙う値ではなく、reviewを人間・Implementerが追跡可能なサイズへ保つsafety boundである。

## 4.1 日本語公開要件

Provider由来のsummary、finding title、explanation、各evidence、任意のsuggested directionは、
公開前の決定論的検証で日本語文字を1文字以上含むことを要求する。

- 日本語文字はひらがな字母U+3041〜U+3096、カタカナ字母U+30A1〜U+30FA、
  CJK統合漢字のUnicode範囲で判定する
- 中黒U+30FB、長音記号U+30FC等の記号だけでは合格しない
- コード、パス、識別子、英語用語の併記は許可する
- 固定句・英単語辞書・内容推測による判定は行わない
- 違反候補は上限付き再生成の対象とし、上限後はBLOCKEDとする

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
- 個別上限内でも全文字列合計が上限を超える候補がrejectされる
- 無害化・整形後のレビュー本文が最終上限を超えて公開されない
- 日本語を含まない公開自然言語がdeterministic validationでrejectされる
- machine marker / reviewed SHA / cycle keyはsanitization対象のprovider textから構築されない
