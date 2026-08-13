# Review Orchestrator Runtime Race Guards

Status: Canonical amendment for Issue #371  
Extends: `docs/architecture/v2/review_orchestrator_implementation.md` Sections 12–13  
Parent contract: `docs/architecture/v2/independent_ai_review_architecture.md`  
Effective: 2026-08-13

## 1. 目的

GitHubのPR更新イベントとReviewer実行が競合した場合でも、Review COMMENT・判定対象SHA・Commit Statusが異なるHEADを指さないことを保証する。

この文書は#371実装中のfinal reviewで発見したrace conditionを設計へ反映するcanonical amendmentである。

## 2. Event Head Preflight

`pull_request_target` event payloadの`pull_request.head.sha`は、workflowが実際に開始するまでに古くなる可能性がある。

Reviewer runtimeはGemini起動や`pending` status永続化より前にGitHub RESTからPRを再取得し、次を検証する。

```text
event_head_sha == live_current_pr_head_sha
```

不一致ならそのrunはstale eventとして停止する。

- Geminiを起動しない
- live current HEADを旧eventの文脈でreviewしない
- current HEADへPASSを投稿しない
- new `synchronize` event側のrunへ処理を委ねる

## 3. Review中のHead再検証

preflight一致後もreview中にHEADが進む可能性があるため、既存#370 contractどおり次の多段チェックを維持する。

1. Context Builderが取得した`ReviewTarget.head_sha`を固定
2. Provider応答後にGitHub live current HEADを再取得
3. Deterministic Validatorで`current == ReviewTarget.head_sha`を要求
4. PR Review COMMENT永続化直前にもう一度HEADを再取得
5. staleなら旧結果をcurrent PASSとして永続化しない

preflightはこの既存stale policyを置換せず、開始時raceを追加で閉じる。

## 4. Commit Status Invariant

Commit Status contextは`yura/independent-ai-review`へ固定する。

statusを書き込むSHAは、当該runが固定したreview target SHAと一致しなければならない。

- start: `pending`
- PASS: `success`
- CHANGES_REQUESTED: `failure`
- BLOCKED / infrastructure error: `error`

GitHub APIへのstatus書込自体が失敗した場合、そのrunを成功扱いしない。特にReviewDecisionがPASSでも、`success` statusを永続化できなければprocessはinternal errorとして終了する。

## 5. Idempotency / Cancellationとの関係

Actions側ではPR番号単位の`concurrency`と`cancel-in-progress: true`を使う。

ただしcancelはbest-effortな実行制御であり、stale safetyのAuthorityにはしない。旧runがcancel前後のraceで開始・継続しても、runtime自身のSHA preflight / revalidationが最終Authorityとなる。

## 6. Unit Acceptance

最低限次を自動検証する。

- event HEAD == live HEAD → review開始可能
- event HEAD != live HEAD → staleとしてreview開始不可
- supported baseは`rebuild/v2-foundation`完全一致のみ
- fork / cross-repository targetを通常経路に昇格しない
- commit status書込失敗を成功扱いしない
- PASS / CHANGES_REQUESTED / BLOCKEDのstatus mappingが固定

## 7. 後続Phase Bへの要求

`main`へ置くtrusted trigger workflowは、本runtimeのpreflightを迂回しない。

workflow filter、GitHub event cancellation、branch filterだけを安全Authorityとして扱わず、必ずbase SHAから本Reviewer runtimeを実行する。
