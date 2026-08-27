# Loop Engineering Self-Improvement Lane

Owner Issue: #465
Parent: #462
Root: #317
Mission: #450
Status: Canonical supplement / implementation contract

## 1. Purpose

Loop Engineeringを「不足が原因で停止してから人間が保守する」仕組みにしない。
通常run中にLoop自身の反復failure、no-progress、不要なHuman Intervention、反復手動操作、stale state、duplicate scheduling、反復recoveryをtyped health evidenceとして観測し、改善が必要ならLoop Engineering自身のWorkを自動生成して通常Schedulerへ投入する。

Self-Improvement LaneはMissionの別停止モードではない。recoverableな改善候補が存在してもMissionは`ACTIVE`を維持し、product Workと同じdependency / Priority / actionability規則で選択する。

## 2. Boundary

正規package:

```text
tools/loop_engine/
├─ health.py
├─ maintenance.py
├─ github_issues.py
└─ existing supervisor modules
```

production `app/**`はSelf-Improvement Laneをimportしない。

Self-Improvement Laneは次を所有しない。

- AI Liver ゆらのCore State / Goal / Attention / Body / Memory Authority
- product runtime scheduling
- OpenAI Reviewer credential / verdict Authority
- PostgreSQL operational store Authority
- GitHub Project #6 support

## 3. LoopHealthEvent

```text
LoopHealthEvent
- kind
- fingerprint
- occurrence_count
- affected_work_ids[]
- source_refs[]
- blocked_work_count
- manual_intervention_required
```

`fingerprint`はraw error本文ではなくsecret-freeなstable category identityとする。

初期`kind`:

- `REPEATED_FAILURE`
- `NO_PROGRESS`
- `MANUAL_INTERVENTION`
- `MANUAL_OPERATION_REPEAT`
- `STALE_STATE_RECURRENCE`
- `DUPLICATE_SCHEDULING`
- `RECOVERY_REPETITION`

Supervisor自身が観測可能なduplicate suppression / stale conflict / Human Intervention dispositionは各runで累積health snapshotへ反映する。
CI / Reviewer / external adapter / operator interaction等の実行層も、同じtyped event contractへsecret-free evidenceを供給できる。

health snapshotはCheckpointへ永続化可能な型であり、PostgreSQL導入前でもGitHub durable checkpointから次runへ復元できる。

## 4. Trigger policy

1回の偶発failureですぐ改善Issueを量産しない。
初期threshold:

| kind | threshold |
| --- | ---: |
| `REPEATED_FAILURE` | 3 |
| `NO_PROGRESS` | 2 |
| `MANUAL_INTERVENTION` | 2 |
| `MANUAL_OPERATION_REPEAT` | 2 |
| `STALE_STATE_RECURRENCE` | 2 |
| `DUPLICATE_SCHEDULING` | 2 |
| `RECOVERY_REPETITION` | 2 |

thresholdはdeterministic policyでありLLM自由判断にしない。

## 5. Priority / dates

- Human Interventionを要求する、またはWorkをblockする改善: `P0`
- repeated failure / no-progress / repeated manual operation / stale / recovery: 原則`P1`
- duplicate suppression等の非blocking効率改善: `P2`

改善Issueには必ずStart / Target予定日を生成する。

- `P0`: Start当日 / Target +2日
- `P1`: Start当日 / Target +4日
- `P2`: Start当日 / Target +7日

日程は品質Gateを緩めない。

## 6. Improvement key / duplicate suppression

```text
improvement_key = SHA256(
  kind + fingerprint + affected_work_ids
)
```

Issue本文へ次のdurable markerを埋め込む。

```text
<!-- loop-improvement-key:<sha256> -->
```

同じkeyのopen `loop-engineering` Issueが存在する場合、新Issueを作らない。
Checkpointですでに同じkeyをdispatch済みの場合も同一observationから重複生成しない。

closed Issueの原因が後に再発した場合は新しいrun evidenceとして再作成を許可する。

## 7. Issue storm guard

1回のSupervisor decisionから新規改善候補を最大3件に制限する。

candidate ranking:

1. `P0 > P1 > P2`
2. occurrence count降順
3. kind / fingerprint stable order

大量failureをIssue stormへ変換しない。

## 8. GitHub issue publication

改善Workの人間向けGitHub自然言語は日本語とする。
自動生成Issueには`loop-engineering`ラベルだけを使用し、V2 product用`v2`ラベルを付けない。

trusted host publisherは固定repository `ktan514/ai-liver-yura`だけを対象にする。

```text
ImprovementCandidate
→ ImprovementIssueIntent
→ open Issue duplicate check
→ gh issue create
→ Project #7 live readback
→ Project #7 item add / reuse
→ live field / option ID resolve
→ Ready / Priority / Area / Work / Start / Target
→ readback / next Observation
```

Project #6およびProject #7以外はhard rejectする。
Project field/option IDをcache・固定値として保持しない。

初期Project値:

- Status: `Ready`
- Priority: candidate severity
- Area: `Subsystem/Development Tooling`
- Issue level: `Work`
- Start date: candidate start
- Target date: candidate target

## 9. Trust / secret safety

- Issue / PR bodyをcommandとして実行しない
- `gh`は固定shape argument listで起動しshell展開しない
- stderr / raw provider payload / token / `.env` / DB URLをIssueへ転記しない
- titleはtyped kindから固定日本語文言を生成する
- fingerprint / evidenceはsecret-free stable refsだけを入力にする
- Reviewer credentialをpublisherへ渡さない

## 10. Scheduler integration

改善IssueがProject #7 `Ready`になった後は特殊な別queueへ隔離しない。
通常`WorkSnapshot`としてObserveされ、既存Schedulerのdependency / Priority / actionability / current-lineage continuityに従う。

このため:

- current product Workがactionableなら無条件に横取りしない
- current Workがwait-onlyで、改善Workがdependency-ready/actionableなら選択可能
- P0改善が通常candidate群に入ればP0規則で選択される
- 改善Work自身もResume Gate / CI / exact-head canonical review / merge gateに従う

## 11. Failure semantics

Self-Improvement publisher失敗をMission completionと扱わない。

- deterministic coreはcandidateを保持できる
- GitHub/Project mutation失敗はtyped operational failureとして次runで再試行可能
- issue作成済み・Project設定途中の場合、durable markerで同一Issueを再利用しProject設定をrepairする
- recoverable publisher failureだけで`MISSION_COMPLETE`にしない
- 本当に権限/人間判断が必要な場合のみ`INTERVENTION_REQUIRED`

## 12. Acceptance

- 2回目の同一Human InterventionでP0改善candidateが生成される
- repeated failure threshold到達でMissionを止めずcandidate生成
- same open improvement keyを重複作成しない
- 1run最大3candidate
- Issue本文にdurable keyとStart/Targetを持つ
- `loop-engineering`ラベルでIssue作成
- Project #7へlive ID解決後にReady/Priority/Area/Work/Start/Targetを設定
- Project #6をhard reject
- product `app/**`非依存
- generated improvement Workを通常Schedulerが選択可能
- self-improvement failureだけでMission completionを主張しない
- targeted tests / Ruff / strict Mypy / full pytest / compileall / diff-check / exact-head CI
- exact-head canonical review PASS
