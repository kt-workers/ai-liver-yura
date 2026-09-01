# V2 Speech Runtime D10 canonical binding

Owner: #348
Canonical authority: `speech_operational_numeric_contracts.md`
Related: `speech_runtime_presentation_contracts.md`, #358
Status: implementation binding

## 1. 目的

#348 の既存 Speech Runtime / Presentation 実装へ、D10 `SpeechRuntimeOperationalPolicy` を正本どおり接続する。

本書は数値を新しく発明しない。production の queue 容量、in-flight 上限、expiry 秒数、repair 回数、speculative TTS 上限はすべて明示的に注入された versioned policy から得る。policy 未指定時に hidden default で継続しない。

## 2. Speech priority

D10 expiry rule は `BACKGROUND | NORMAL | FOREGROUND | DIRECT_USER` を exactly once 覆う必要があるため、#348 に `SpeechCandidatePriority` を置く。

- `BACKGROUND`
- `NORMAL`
- `FOREGROUND`
- `DIRECT_USER`

これは LLM Provider scheduling 用 `LLMPriority` とは別の Speech Runtime Authority である。

必要な scheduling projection は明示変換のみ許す。

- `BACKGROUND -> LLMPriority.BACKGROUND`
- `NORMAL -> LLMPriority.NORMAL`
- `FOREGROUND -> LLMPriority.FOREGROUND`
- `DIRECT_USER -> LLMPriority.FOREGROUND`

raw text、candidate id、発話内容から `DIRECT_USER` を推測しない。

`SpeechPreparationRequest.priority` と `PreparedSpeechCandidate.priority` は `SpeechCandidatePriority` を保持する。

## 3. Operational policy

```text
SpeechRuntimeOperationalPolicy
- policy_id
- policy_revision
- prepared_queue_capacity
- max_in_flight_preparations
- max_background_in_flight_preparations
- max_regeneration_attempts
- expiry_rules
- speculative_tts_limit
- queue_overflow_policy
```

`queue_overflow_policy` は D10 Section 4 の closed enum:

- `REJECT_NEW`
- `EVICT_LOWEST_PRIORITY_OLDEST`

validation:

- revision は non-negative concrete int
- queue capacity / max in-flight は concrete int >= 1
- background in-flight / regeneration / speculative limit は concrete int >= 0
- background in-flight は total in-flight を超えない
- expiry rule 秒数は bool を除く finite number > 0
- expiry rule は4 priorityを重複なく exactly once 覆う
- policy が無い場合にproduction defaultを生成しない

## 4. Policy generation binding

`SpeechPreparationRequest` と `PreparedSpeechCandidate` は `runtime_policy_id` / `runtime_policy_revision` を必須provenanceとして保持する。

Runtimeへ登録・queue・revalidation・Presentation commitする時点で current policy generationとexact一致を確認する。

async wait中にrevisionが変わったold candidate/resultをnew policyへ付け替えない。old candidateはtyped stale/fail-closed経路へ閉じる。

## 5. Expiry authority

expiryは timezone-aware absolute instant のelapsed ageだけで判定する。

```text
age_seconds = UTC(now_absolute) - UTC(candidate.created_at)
expired = age_seconds > rule.max_candidate_age_seconds
```

- `<` は有効
- `==` も有効
- `>` だけexpired
- `expires_at` のwall-clock field比較をexpiry Authorityにしない
- `now < created_at` はclock contract violationとしてfail-closed

Runtime clockはテスト可能なaware-datetime sourceを注入可能にする。system既定clockはpolicy値ではないため利用可。

## 6. Prepared queue

queue entryは以下を保持する。

- candidate_id
- generation
- SpeechCandidatePriority
- prepared_at

canonical pop order:

1. priority descending (`DIRECT_USER > FOREGROUND > NORMAL > BACKGROUND`)
2. same priorityは `prepared_at` ascending
3. tieは `candidate_id` Unicode code-point lexicographic ascending

terminal/stale/expiredはadmission/pop前にpurge eligibilityへ回す。

capacity超過時は `SpeechQueueAdmissionResult` を返し、silent dropしない。

```text
SpeechQueueAdmissionResult
- admitted_candidate_id?
- rejected_candidate_id?
- evicted_candidate_id?
```

`REJECT_NEW` はnew candidateをrejectする。

`EVICT_LOWEST_PRIORITY_OLDEST` はqueue中lowest-priority groupのoldest 1件だけを候補にする。new candidateがその候補より低priorityならreject、同priority以上ならevictしてadmitする。presenting candidateはqueue外なので対象外。

## 7. Preparation admission

`max_in_flight_preparations` をglobal active preparation上限、`max_background_in_flight_preparations` を `SpeechCandidatePriority.BACKGROUND` の追加上限として扱う。

NORMAL / FOREGROUND / DIRECT_USER はbackground capを消費しないがglobal capは消費する。

## 8. Repair

repair可否はcandidateの `repair_count` と current policy `max_regeneration_attempts` で判定する。

- `repair_count < max_regeneration_attempts` の時だけ次のregenerationを開始
- attempt番号は `repair_count + 1`
- 0/1/Nを扱う
- `repair_count` はProvider retry countやcandidate generation numberから推測しない
- current canonicalに無いrepair evidence件数上限は#348で追加しない
- max到達後はtyped final rejectionへ閉じ、generic phraseを補作しない

same-rejection early-stopは現行#348実装に存在せず、D10も「使う場合のみversioned SpeechRepairPolicy」としているため本変更では導入しない。

## 9. Speculative TTS

`speculative_tts_limit` はcandidate単位ではなくSpeech Runtime全体の、semantic acceptance前TTS request同時数である。

- `SPECULATIVE_AFTER_PERFORMANCE` かつ verifier未accept のrequestだけcountする
- limit 0ならspeculative requestを開始しない
- semantic accepted後のrequired synthesisはcountしない
- task完了 / 失敗 / cancel時にfinallyでslotをreleaseする
- required foreground synthesisはspeculative slot不足でblockしない

#358 Provider内部concurrencyやmappingは変更しない。

## 10. Compatibility

既存のD8/D9責務分離、generation fence、SemanticAcceptance、prepared audio discard、Presentation report truth boundaryは維持する。

旧constructorのhidden numeric defaultはproduction compatibilityとして残さない。テストは明示的なtest policy fixtureを使用する。

## 11. Required tests

- strict int/float validationとbool/NaN/Infinity reject
- expiry rule exactly-once coverage
- policy missing/freshness fail-closed
- expiry `< / == / >`、timezone offsetが同一UTC instantとして扱われること
- queue deterministic order
- `REJECT_NEW`
- `EVICT_LOWEST_PRIORITY_OLDEST`、lower priority new reject、admission result IDs
- preparation active total/background 0/positive boundary
- regeneration max 0/1/N
- speculative limit 0/positive、global count release、accepted required synthesis非計上
- existing Speech Runtime full regression
