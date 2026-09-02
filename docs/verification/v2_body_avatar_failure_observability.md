# V2 Body / Avatar Verification Failure Observability

Owner Issue: #545
Related: #341 / #346 / #544
Verification-only branch: `test/341-346-avatar-stick-verification`
Status: Verification Harness Design

## 1. Purpose

Human Verification中にproduction Body runtimeがfatalで停止した場合、Browserが単に静止したように見えることを禁止する。またBrowser reload/SSE reconnectによるTCP resetをproduction failureと混同しない。

この文書はverification harnessの観測性だけを定義し、#339/#340/#341/#346のproduction error semanticsは変更しない。

## 2. Client disconnect

`ThreadingHTTPServer`では、SSE write中だけでなく次request lineを読む前段の`socketserver`層で`ConnectionResetError`が発生しうる。

Browser reload / tab close / EventSource reconnectに起因する`ConnectionResetError`は:

- verification server processを停止させない
- Body runtimeを停止させない
- terminalへfull tracebackを出さない
- production Body failureとして記録しない

`VerificationHTTPServer.handle_error()`でcurrent exceptionが`ConnectionResetError`の場合だけ静かにreturnする。それ以外のserver-side exceptionは親実装へ渡し、未知のHTTP failureを握り潰さない。

## 3. Body runtime fatal

`VerificationEngine`のworker threadでfatal exceptionが発生した場合:

- snapshot `ready=false`
- snapshot `fatal_error="<Type>: <message>"`
- terminalへ同じsanitized fatal summaryをstderrで即時flush
- 最終frame/revision/controller/session/planner/realtime evidenceは可能な限りsnapshotに保持
- HTTP/SSE server自体は生存し、Browserと`/api/snapshot`からfailure evidenceを読める

production exceptionをverification harnessが成功へ変換してはならない。

## 4. Browser presentation

`fatal_error`がnon-nullなら:

- top connection badgeを`Runtime FAIL`へ変更
- persistent fatal bannerを表示
- fatal summaryを診断欄にも残す
- Canvasの最終有効frameは証拠として保持してよいが、animation継続中のようには見せない

Human verifierが「画面が固まっただけ」と誤認しないことがacceptanceである。

## 5. Regression

Verification-only testsで最低限:

1. `_publish_fatal(RuntimeError("boom"))` がsnapshotとstderrの両方にfatalを公開する。
2. `VerificationHTTPServer.handle_error()` が`ConnectionResetError`だけをtracebackなしで無視する。
3. 非ConnectionResetのHTTP exceptionは親`handle_error`へ委譲する設計を維持する。

## 6. Production blocker separation

#545で発見したproduction Body failureは#546へ分離済み。

#545は#546の物理制御バグをverification側でcatchして継続する修正を行わない。#546が正本production ownerで修正し、#544はその修正を再合成してHuman Verificationを再実施する。
