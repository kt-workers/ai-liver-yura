# Speech Runtime D10 Operational Policy Binding — Issue #348

Owner: #348
Shared owner: #358 for TTS preparation limits
Canonical numeric source: `speech_operational_numeric_contracts.md`

## Purpose

既存のSpeech Runtime / Presentation Authorityを再実装せず、D10で確定した数値契約をqueue、prepared candidate、revalidation、repair、speculative TTS preparationへ同一Policy generationとして接続する。

## Policy authority

Runtimeは次のtyped policyを1つのgenerationとして利用する。

```text
SpeechRuntimeOperationalPolicy
- policy_id
- policy_revision
- queue_max_candidates = 8
- queue_max_consecutive_foreground = 3
- prepared_candidate_ttl_ms = 15000
- revalidation_max_age_ms = 3000
- repair_max_generation_attempts = 1
- repair_evidence_max_refs = 64
- speculative_tts_parallelism_per_candidate = 1
```

全intは`type(value) is int`を要求し、boolを拒否する。
`prepared_candidate_ttl_ms > revalidation_max_age_ms`を要求する。
repair generationとspeculative TTS parallelismはv1では1固定とする。

## Prepared candidate monotonic contract

wall clock `created_at` / `updated_at` / `expires_at`は監査・互換情報としてのみ保持できる。
TTL / revalidation freshnessのAuthorityには使わない。

D10 generation-bound candidateは次を保持する。

```text
runtime_policy_id
runtime_policy_revision
created_mono_ms
prepared_mono_ms
revalidation_started_mono_ms
prepared_ttl_ms
revalidation_max_age_ms
```

- prepared expiry: `now_mono_ms - prepared_mono_ms >= prepared_ttl_ms`
- revalidation age failure: `now_mono_ms - revalidation_started_mono_ms > revalidation_max_age_ms`
- monotonic値は0以上のstrict int。boolは禁止。
- new production registrationはcurrent runtime policy generationをsnapshotする。
- legacy constructor compatibilityは既存試験/lineage移行用だけであり、新しいproduction rootのAuthorityにしない。

## Policy freshness

`SpeechRuntime`はcurrent `SpeechRuntimeOperationalPolicy`を保持する。
Policy generationがcandidate snapshotから変化した場合、旧candidateを新しいduration/limitへ付け替えない。
queued/revalidation/presentationへ進めずstale/supersededとして再準備対象にする。

## Queue

`PreparedSpeechQueue`のproduction constructorはPolicyを受け、
`queue_max_candidates`と`queue_max_consecutive_foreground`を同じgenerationから使用する。
旧int constructorは移行互換に限る。

## Repair

`SpeechSemanticRepairExecutor`は同じPolicyから:

- generation attempt上限 = 1
- evidence refs上限 = 64

を適用する。evidence overflowを先頭Nへ切らない。

## Speculative TTS

#348はTTS Providerの内部制約を所有しない。
Runtime orchestrationとして同一candidate/generationのspeculative TTS preparationをPolicy上限以内にする責務だけを持つ。
v1は1本固定であり、同じcandidate/generationへ2本目を開始しない。

## Failure semantics

容量・generation・age違反はfail-closed。
期限切れcandidate、old policy generation、revalidation age超過、repair evidence overflow、speculative TTS並列超過をsilent clampやfirst-Nでsuccessにしない。

## Required tests

- Policy default値とstrict int/bool拒否
- TTL `14999 / 15000 ms`
- revalidation age `3000 / 3001 ms`
- wall clock変動がTTL判定へ影響しない
- policy revision変更後のold candidate拒否
- queue 8/9、foreground fairness 3
- repair evidence 64/65、generation 1固定
- speculative TTS 1/2
- legacy compatibility pathがproduction Policy値を書き換えないこと
