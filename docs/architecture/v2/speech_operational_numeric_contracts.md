# V2 Speech Runtime / TTS Operational Numerical Contracts

Owners: #348 / #358
Related: `speech_runtime_presentation_contracts.md`, `tts_provider_contracts.md`, `speech_performance_contracts.md`, `runtime_operational_numeric_contracts.md`
Design gate: #445 D10
Status: Canonical Supplement / implementation-decidability correction

## 1. 目的

Speech Runtimeのrepair回数、prepared queue、expiry、speculative preparation上限と、#358のnormalized performance→Provider parameter mappingを、hidden constantやProvider SDK defaultへ委ねずversioned policyとして固定する。

Speech semantic/language/performance Authorityは既存ownerのまま維持する。

## 2. Strict numeric rule

count/revisionはconcrete `int`、seconds/parameter rangeはfinite numberを要求し、bool、NaN、±Infinityを拒否する。

## 3. SpeechRuntimeOperationalPolicy

```text
SpeechRuntimeOperationalPolicy
- policy_id
- policy_revision: non-negative int
- prepared_queue_capacity: int >= 1
- max_in_flight_preparations: int >= 1
- max_background_in_flight_preparations: int >= 0
- max_regeneration_attempts: int >= 0
- expiry_rules: unique tuple[SpeechExpiryRule]
- speculative_tts_limit: int >= 0

SpeechExpiryRule
- priority: BACKGROUND | NORMAL | FOREGROUND | DIRECT_USER
- max_candidate_age_seconds: finite float > 0
```

Rules:

- `max_regeneration_attempts`はinitial #330 realizationの後に追加で許可されるregeneration回数。`0`ならrepair regenerationなし。
- supported priorityを`expiry_rules`がexactly once覆う。
- candidate ageは`now_absolute - created_at_absolute`で測る。wall-clock field比較をしない。
- `age > max_candidate_age_seconds`でexpired。**等値時点はまだ期限内**とする。
- policy missing/invalid時、Speech Runtimeはhidden queue/repair/TTL値で継続せずconfiguration-degraded/fail-closedとする。既に開始済みPresentationのactual effect reconciliationは継続する。

## 4. Prepared queue admission

queueは#322 bounded primitiveを使うが、Speech candidate semanticsは#348が所有する。

Canonical order:

1. terminal/stale/expired candidateをpurge eligibilityへ回す。
2. candidate priorityでdescending。
3. same priorityは`prepared_at` ascending。
4. tieは`candidate_id` Unicode code-point lexicographic ascending。

`prepared_queue_capacity`を超える新candidateのhandlingはclosed `SpeechQueueOverflowPolicy`として別policy field/enumで明示する。

```text
REJECT_NEW
EVICT_LOWEST_PRIORITY_OLDEST
```

`EVICT_LOWEST_PRIORITY_OLDEST`:

- queue中のlowest priority groupからoldest candidateを1件だけsupersedeして新candidateをadmitできる。
- 新candidateがeviction対象より低priorityならevictせずnewをreject。
- DIRECT_USER等の意味をcandidate textから推測しない。
- presenting candidateはprepared queue eviction対象ではない。

silent dropは禁止する。admission resultにadmitted/rejected/evicted candidate IDsを残す。

## 5. Repair loop

#363 rejectionが#348 canonicalでrepairableと分類された場合のみregenerationできる。

```text
regeneration_index = 1..max_regeneration_attempts
```

- 同じrejection classのearly-stop ruleを使う場合、versioned `SpeechRepairPolicy`へ`stop_after_same_rejection_count: int >= 1`として明示する。
- repair attemptごとに新しいutterance/performance/audio identityを必須とする。
- attempt counterをProvider retry counterと混同しない。
- max到達後はgeneric phraseを補作せずtyped terminal rejection/failureへ閉じる。

## 6. Speculative TTS bound

`speculative_tts_limit`は同時にcandidate-scopedで準備可能な**semantic acceptance前の**TTS request数のglobal Speech Runtime上限。

- `0`でspeculative synthesis禁止。
- semantic accepted後のrequired synthesisはこのspeculative countには含めず、#322/#358のprovider concurrency boundへ従う。
- candidate cancel/reject/supersede時はspeculative slotをreleaseしartifactをdiscardする。
- background speculative requestがforeground required requestをstarveしない。

## 7. TTS Provider performance mapping

#358は各normalized `PerformanceIntentVector` axisをProvider parameterへ変換する際、immutable/versioned `TTSPerformanceMappingPolicy`を必須とする。

```text
TTSPerformanceMappingPolicy
- mapping_id
- mapping_revision: non-negative int
- provider_id
- provider_revision
- dimension_rules: unique tuple[TTSParameterMappingRule]

TTSParameterMappingRule
- dimension
- provider_parameter
- normalized_min: -1.0
- normalized_neutral: 0.0
- normalized_max: 1.0
- provider_min: finite float
- provider_neutral: finite float
- provider_max: finite float
- monotonicity: INCREASING | DECREASING
```

Provider rangeはexplicit configurationであり、SDK documentationからruntime introspectionしてDomain semanticを変更しない。

### 7.1 Piecewise-linear mapping

normalized `x ∈ [-1,1]`に対し、neutralを保つpiecewise linear mappingを正本とする。

For `x <= 0`:

```text
t = x + 1                # [0,1]
y = provider_min + t * (provider_neutral - provider_min)
```

For `x > 0`:

```text
t = x                    # (0,1]
y = provider_neutral + t * (provider_max - provider_neutral)
```

`DECREASING` ruleではpolicy validation時に`provider_min >= provider_neutral >= provider_max`を要求し、同じ式を用いる。

`INCREASING`では`provider_min <= provider_neutral <= provider_max`。

Rules:

- input normalized range外をsilent clampしない。#331 contract violationとしてfail-closed。
- computed valueがProvider accepted range外になるpolicyはconstructorでreject。
- provider parameter名やdimension名のsubstringでmappingを選ばない。
- unsupported dimensionはmapping ruleを捏造せず、#358 canonicalのtyped degradationへ回す。
- provider mapping revisionはaudio artifact/cache identityへbindする。

## 8. Segment timing-like performance values

`boundary_strength`, `pause_after_intent`, `duration_bias`, `emphasis_strength`, `hesitation_strength`等normalized valuesをProvider-specific milliseconds/scaleへ投影する場合も、Section 7と同じ明示ruleを使うか、dimension専用のversioned mapping ruleを定義する。

- `pause_after_intent`からmillisecondsを固定倍率でhidden計算しない。
- actual phoneme/mora/viseme timingはProvider observationであり、このmapping policyから捏造しない。

## 9. TTS retry/backoff

#358 request retryは`runtime_operational_numeric_contracts.md`の`DependencyRetryPolicy`をprovider/dependency generationへbindして使用する。

- `max_retry_attempts`はinitial synthesis failure後の追加retry数。
- exact exponential delay formula、no hidden jitter、shutdown/cancellation interruptionを共有する。
- request permanent invalid/binding/schema errorsはretryしない。
- synthesis requestのown deadlineがある場合、retry sleep後にremaining deadlineを再評価し、失効後はProvider callを開始しない。

## 10. Policy freshness

SpeechPreparationRequestはSpeech runtime policy identity/revisionをgenerationへbindする。

TTSSynthesisRequest/PreparedAudioArtifactはmapping identity/revisionとretry policy identity/revisionをprovenanceへ保持する。

- async wait中にpolicy revisionが変わってもold artifact/resultをnew revisionへ付け替えない。
- mapping revision変更はaudio-affecting generation changeであり、old cache/artifactをcurrent mappingの成果物として再利用しない。
- Presentation commitはcurrent policy compatibilityを#348 live revalidationで確認する。

## 11. Required tests

- queue capacity/parallel count/repair/speculation strict validation
- expiry: `<`, `==`, `>`境界とUTC absolute instant
- deterministic queue order / eviction / no silent drop
- regeneration max 0/1/N、same rejection early stop
- speculative limit 0/positive、foreground starvationなし
- provider mapping -1/0/+1 exact endpoints
- positive/negative intermediate piecewise mapping
- increasing/decreasing validation
- normalized out-of-rangeをclampしない
- unsupported dimension typed degradation
- mapping revisionでcache/artifact identity変化
- retry/backoffを#350 canonicalと共有しunbounded retryなし
