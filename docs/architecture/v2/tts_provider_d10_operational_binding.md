# V2 TTS Provider D10 operational binding

Owner: #358
Existing implementation: PR #448（merge済み）
Canonical authority:
- `tts_provider_contracts.md`
- `speech_operational_numeric_contracts.md`
- `runtime_operational_numeric_contracts.md`
Related: #331 / #348 / #350
Status: implementation binding

## 1. 目的

PR #448で実装済みのTTS Provider境界、音声artifact、発音override、timing正規化、candidate単位discard、再生非所有境界を維持したまま、D10で追加された次の不足だけを補完する。

- normalized performanceからProvider値への変換を明示versioned policyへする
- silent clampとhidden `* 2 - 1`変換を除去する
- retry/backoffを#350 `DependencyRetryPolicy`へ統一する
- request/artifactへmapping/retry policy provenanceを保持する
- retry sleep後のrequest deadlineを再確認する

既存TTS機能の全面再実装は行わない。

## 2. Policy分離

### 2.1 TTSPerformanceMappingPolicy

D10正本どおり、音声へ影響する変換規則だけを所有する。

```text
TTSPerformanceMappingPolicy
- mapping_id
- mapping_revision
- provider_id
- provider_revision
- signed_rules[]
- unit_rules[]
```

`signed_rules`は入力範囲`[-1, 0, +1]`を持つ`TTSParameterMappingRule`。

```text
TTSParameterMappingRule
- dimension
- provider_parameter
- provider_min
- provider_neutral
- provider_max
- monotonicity: INCREASING | DECREASING
```

変換式は`speech_operational_numeric_contracts.md` Section 7.1をexactに使用する。

入力が`[-1,+1]`外ならsilent clampせずfail-closedする。

### 2.2 0..1 segment値

既存`SpeechPerformanceSegment`の次の値は正本上`[0,1]`であるため、hidden `*2-1`を使用しない。

- `boundary_strength`
- `pause_after_intent`
- `duration_bias`
- `emphasis_strength`
- `hesitation_strength`

D10 Section 8が許可するdimension専用versioned ruleとして`TTSUnitParameterMappingRule`を定義する。

```text
TTSUnitParameterMappingRule
- dimension
- provider_parameter
- source_min = 0.0
- source_neutral
- source_max = 1.0
- provider_min
- provider_neutral
- provider_max
- monotonicity
```

`source_neutral`を明示し、左右のpiecewise-linear mappingを行う。これにより旧実装の挙動を意味を変えず明示化する。

- boundary / duration / emphasis / hesitation: source neutral `0.5`
- phrase pause: source neutral `0.0`

pitch anchorの`relative_pitch`は`[-1,+1]`なのでsigned ruleを使う。

Rule選択はexact dimension identityで行い、文字列substringから推測しない。

### 2.3 TTSProviderOperationalPolicy

mappingやretryとは独立して、Provider呼出そのものの運用境界だけを持つ。

```text
TTSProviderOperationalPolicy
- policy_id
- policy_revision
- provider_id
- provider_revision
- timeout_seconds
- max_foreground_synthesis
- max_speculative_synthesis
```

全数値はstrictに検証し、bool / NaN / ±Infinity / invalid countを拒否する。

production hidden defaultを持たない。

既存`TTSSynthesisRequest.provider_config_revision`は、音声へ影響するProvider設定の既存identityであり、`TTSProviderOperationalPolicy.policy_revision`とは別Authorityである。両revisionの数値一致を要求しない。`provider_config_revision`は従来どおりartifact/cache identityへ保持し、運用Policy generationはimmutableなAdapter instanceへbindする。

### 2.4 DependencyRetryPolicy

retry/backoffは#358独自の`max_attempts`や固定sleepを持たず、#350の`DependencyRetryPolicy`を必須注入する。

- `dependency_id == provider_id`
- initial synthesis + `max_retry_attempts`回まで追加retry
- delayは#350 canonical `delay_for(n)`
- hidden jitterなし
- `retry_enabled=false`またはnon-retryableなら追加retryなし
- permanent request/binding/schema failureはretryしない

## 3. Request / Artifact provenance

`TTSSynthesisRequest`へ次を追加する。

```text
- mapping_id
- mapping_revision
- retry_policy_id
- retry_policy_revision
- deadline_at?
```

`PreparedAudioArtifact`へ次を追加する。

```text
- mapping_id
- mapping_revision
- retry_policy_id
- retry_policy_revision
```

Artifactを新しいmapping/retry generationへ付け替えない。

cache identityには音声内容へ影響するmapping identity/revisionを含める。retry policyは音声内容を変えないためcache keyの音声identityには含めないが、artifact provenanceには必ず保持する。

既存`provider_config_revision`と`pronunciation_config_revision`も音声内容に影響する既存identityとして保持する。これらをTTS運用Policyのrevisionへ読み替えない。

## 4. Freshness / deadline

Adapter instanceはconstructorで受け取ったpolicy generationに固定する。policy更新は同じinstanceをmutationせず、新しいAdapter generationを構成する。

したがってold async resultはold Adapter generationのprovenanceを保持し、新revisionへrebindingされない。

Provider call開始前にrequestのmapping/retry provenanceとAdapter policy generationのexact一致、およびProvider identity/revision互換を確認する。独立Authorityである`provider_config_revision`とoperational policy revisionの数値一致は要求しない。

retry sleep後は:

1. cancellation/shutdown状態を尊重する
2. `deadline_at`がある場合、current absolute timeで再評価する
3. deadline到達/超過なら次Provider callを開始せず`REQUEST_TIMEOUT`へ閉じる

## 5. 既存責務を維持するもの

- #358はplaybackを開始しない
- speculative synthesisからBody/viseme副作用を出さない
- pronunciation overrideは表示/semantic textを変更しない
- timing unavailable時に架空timingを作らない
- artifactはcandidate-scopedでdiscard可能
- foreground/speculative concurrencyは独立laneとして維持する
- provider raw exception/body/header/secretをpublic resultへ出さない

## 6. 移行

旧`TTSProviderMappingPolicy`に混在しているmapping / retry / timeout / concurrency authorityを分解する。

productionの`revision_1()`固定値は削除し、必要な値はtest fixtureへ移す。

既存テストは同じシナリオを明示policy fixtureへ移行し、機能回帰を保持する。

## 7. 必須試験

- signed mapping -1 / 0 / +1 exact endpoint
- signed mapping正負中間値
- increasing / decreasing validation
- signed out-of-rangeをrejectしsilent clampしない
- unit mapping 0 / neutral / 1 endpoint
- phrase pauseのsource neutral 0.0
- exact dimension lookup、unsupportedはtyped degradation
- mapping revision変更でcache identityが変化
- request/artifactへmapping/retry provenance保持
- `provider_config_revision`とoperational policy revisionの独立性
- retry 0 / 1 / Nと#350 exact backoff
- non-retryableでretryなし
- retry sleep後deadline失効ならProvider未呼出
- timeout / cancellation / shutdown pending task 0
- foreground requiredがbackground speculativeにstarveされない
- 既存pronunciation/timing/artifact discard回帰
