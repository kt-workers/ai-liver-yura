# V2 TTS Provider Contracts

Owner Issue: #358
Parent: #356
Upstream: #331, #348
Downstream: #348, #340, Presentation Adapter
Related:
- `docs/architecture/v2/speech_performance_contracts.md`
- `docs/architecture/v2/speech_runtime_presentation_contracts.md`
- `docs/architecture/v2/runtime_lifecycle_contracts.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

#358は、`CharacterUtterance`とengine-independent `SpeechPerformancePlan`を、VOICEVOX等の具体TTS Providerへ安全に変換し、**再生前のaudio artifactと利用可能なpronunciation/timing情報**を返すInfrastructure Adapter境界である。

```text
CharacterUtterance
+ SpeechPerformancePlan
+ TTSVoiceBinding
+ TTSCapabilityView
+ pronunciation configuration
        ↓
TTS Provider Adapter
        ↓
PreparedAudioArtifact
+ SpeechTimingTrack?
+ TTSSynthesisResult
        ↓
#348 Presentation Runtime
        ↓ committed/started only
#340 viseme realtime
```

TTS synthesis successはPresentation successやActual Speech Factを意味しない。

---

## 2. Authority boundary

#358 owns:
- provider-specific request mapping
- provider voice/speaker/style binding resolution
- provider performance parameter mapping/clamping
- synthesis invocation
- timeout / cancellation / bounded retry
- provider response normalization
- audio artifact creation/reference
- pronunciation/timing extraction when available
- provider capability degradation diagnostics

#358 does not own:
- What-to-say (#362)
- Character words / language (#330)
- Character Voice Style semantics (#355)
- engine-independent performance intent (#331)
- semantic acceptance (#363)
- Presentation commit / queue (#348)
- actual mouth/Body motion (#340)
- current Emotion/Goal/Attention authority

---

## 3. TTSVoiceBinding

Character DefinitionのVoice Styleとprovider bindingを分離する。

```text
TTSVoiceBinding
- binding_id
- character_id
- provider_id
- provider_voice_ref
- binding_revision
- locale
- enabled
- metadata_refs[]
```

`provider_voice_ref`はInfrastructure configurationでありCharacter Bible factではない。

例:
- VOICEVOX speaker/style ID
- cloud TTS voice name
- local model checkpoint reference

禁止:
- `CharacterVoiceStyleProfile`へspeaker/style IDを格納する
- character age/gender/personalityからprovider voice IDを自動推測する
- unavailable binding時に別voiceを無断選択する

Alternate/fallback bindingを使う場合は明示的なInfrastructure policyとして設定する。

---

## 4. TTSCapabilityView

Provider固有API objectをDomainへ出さず、#358内部またはInfrastructure public read modelでbounded capabilityを表す。

```text
TTSCapabilityView
- provider_id
- provider_revision
- voice_binding_revision
- supports_rate
- supports_pitch_center
- supports_pitch_range
- supports_loudness
- supports_breathiness
- supports_phrase_pause
- supports_pronunciation_override
- supports_phoneme_timing
- supports_mora_timing
- supports_viseme_timing
- supports_streaming_audio
- max_text_length?
```

Capabilityはactual provider availabilityとは分離する。

```text
capability supported
!= provider currently available
```

---

## 5. Synthesis request

```text
TTSSynthesisRequest
- request_id
- candidate_id
- utterance_id
- performance_plan_id
- voice_binding_id
- voice_binding_revision
- provider_revision
- character_id
- text_segments[]
- performance_segments[]
- pronunciation_overrides[]
- priority
- interruptibility
- deadline?
- created_at
- trace_id
```

Identity requirements:
- text segment IDs match CharacterUtterance exactly.
- performance segment refs match the same utterance exactly.
- request cannot mix utterance A with performance plan B.
- voice binding character_id must match utterance character_id.

Provider request is generated only after this structural validation.

---

## 6. Text / pronunciation boundary

Display/semantic text remains #330 `CharacterUtterance`.

#358 may apply pronunciation-only configuration without mutating CharacterUtterance.

```text
PronunciationOverrideView
- override_id
- surface
- reading
- locale
- source_owner
- revision
```

Use cases:
- 固有名詞の読み
- provider辞書で誤読する語
- Character名等の安定した発音

Rules:
- pronunciation override changes phonetic realization only.
- it does not change semantic/display text.
- raw ad-hoc user text replacement dictionary is not an open-ended semantic mechanism.
- unknown reading must not be guessed into a canonical fact.

---

## 7. Performance mapping

#331 normalized `PerformanceIntentVector` / segment intentをprovider parameterへ変換する。

Mapping characteristics:
- provider-specific
- bounded/clamped
- versioned/configurable
- testable
- no semantic text rewrite

Example concept:

```text
normalized pace [-1,+1]
→ provider-specific allowed speed range
```

The exact mapping is Adapter configuration, not Core Character canonical.

### Unsupported dimension

If provider lacks a dimension:
- omit/neutralize only that provider control
- record typed degradation
- do not alter CharacterUtterance text
- do not rewrite the canonical SpeechPerformancePlan

---

## 8. Synthesis lifecycle

```text
CREATED
→ QUEUED
→ SYNTHESIZING
→ SUCCEEDED
```

Alternate terminal:

```text
CANCELLED
TIMED_OUT
PROVIDER_UNAVAILABLE
PROVIDER_REJECTED
INVALID_REQUEST
FAILED
```

No retry state may grow without bound.

Retry policy:
- only retry retryable operational failure classes
- bounded attempts/backoff
- cancellation/shutdown interrupts retry wait
- permanent configuration/request errors are not blind-retried

---

## 9. PreparedAudioArtifact

Successful synthesis produces an immutable artifact reference.

```text
PreparedAudioArtifact
- audio_artifact_id
- request_id
- candidate_id
- utterance_id
- performance_plan_id
- voice_binding_id
- voice_binding_revision
- provider_revision
- audio_ref
- audio_format
- sample_rate?
- channels?
- duration_ms?
- content_digest
- created_at
```

`audio_ref` points to bounded storage/stream resource; raw binary is not embedded in Domain DTOs.

Artifact identity is exact.

It cannot be reused for a different:
- utterance
- performance plan
- voice binding revision
- provider mapping revision
- pronunciation configuration revision when that changes audio

Prepared artifact is not Presentation Fact.

---

## 10. SpeechTimingTrack

When provider gives trustworthy timing, normalize it into provider-independent track.

```text
SpeechTimingTrack
- timing_track_id
- audio_artifact_id
- source_kind
- quality
- units[]
- created_at
```

Unit:

```text
SpeechTimingUnit
- unit_id
- segment_id
- kind
- symbol
- start_ms
- end_ms
- confidence?
```

Possible `kind`:
- PHONEME
- MORA
- VISEME
- WORD_BOUNDARY

Provider-specific internal IDs do not leak.

Timing must be monotonic and within artifact duration when duration is known.

---

## 11. Timing unavailable / approximation boundary

If provider offers no trustworthy timing:
- synthesis may still succeed.
- `SpeechTimingTrack` is absent.
- typed degradation reason `TIMING_UNAVAILABLE` is returned.

#358 does not fabricate exact phoneme timestamps from text alone and call them actual provider timing.

If a later separate approximation component is adopted, its output must be marked `APPROXIMATED` and must not be confused with provider-observed timing.

#340 decides how to degrade viseme behavior using the typed timing quality; it does not require #358 to lie about exact timing.

---

## 12. TTSSynthesisResult

```text
TTSSynthesisResult
- request_id
- status
- audio_artifact_ref?
- timing_track_ref?
- applied_dimensions[]
- degraded_dimensions[]
- degradation_reasons[]
- operational_diagnostic?
- attempts
- started_at?
- completed_at
```

`SUCCEEDED` means audio preparation succeeded.

It does not mean:
- verifier accepted
- candidate is still current
- playback started
- Yura actually said the utterance

---

## 13. Operational failures

Closed Infrastructure failure categories include at minimum:
- INVALID_BINDING
- INVALID_REQUEST
- PROVIDER_UNAVAILABLE
- RATE_LIMITED
- REQUEST_TIMEOUT
- PROVIDER_SERVER_ERROR
- PROVIDER_REJECTED
- AUDIO_DECODE_OR_STORAGE_FAILED
- CANCELLED

Provider-specific raw exception type/message/body/headers are not Domain error payload.

Safe diagnostics may include:
- provider_id
- HTTP status if safe/applicable
- request ID supplied by provider if safe
- attempt count
- retryable
- sanitized category

Never expose:
- API key
- Authorization header
- full raw provider response
- secret URL/token

---

## 14. Speculative synthesis

#348 may start #358 before semantic verifier acceptance when a closed policy permits.

Requirements:
- artifact stays candidate-scoped
- no auto-play side effect
- no Body viseme publication before Presentation commit/start
- cancellation/supersede/verifier rejection discards artifact

A speculative synthesis result cannot call Presentation by itself.

---

## 15. Caching

Caching is optional derived optimization.

Cache key must include all audio-affecting identity inputs, at minimum:
- exact utterance text/content digest
- performance_plan_id or equivalent performance digest
- voice_binding revision
- provider mapping/config revision
- pronunciation configuration revision

Do not cache by plain text alone when performance differs.

Cache hit is still subject to candidate freshness and Presentation revalidation.

---

## 16. Cancellation / concurrency

- each synthesis request is independently cancellable where provider permits.
- cancellation of candidate A does not cancel unrelated B.
- slow TTS does not block Input Meaning/Executive/Body/current Presentation.
- bounded provider concurrency/backpressure applies.
- background speculative synthesis may not starve foreground response synthesis.
- shutdown cancels/settles pending synthesis and retry waits without leaving pending tasks.

Provider SDK calls occur outside Core locks.

---

## 17. Presentation boundary

#358 never starts audible playback as part of synthesis API.

```text
#358 prepared audio
→ #348 revalidation / Presentation commit
→ Presentation Adapter playback
```

This separation is mandatory for:
- semantic verifier fail
- stale candidate discard
- user interruption
- priority arbitration
- speculative preparation

---

## 18. #340 viseme boundary

Only Presentation-committed/started audio timing is eligible for actual mouth motion.

```text
SpeechPresentation STARTED
+ SpeechTimingTrack
+ actual presentation start time
→ #340 canonical viseme realtime input
```

#358 does not move Body joints/parameters.

Provider viseme IDs, if any, are normalized before crossing the Infrastructure boundary.

---

## 19. Voice availability / fallback

If configured Yura voice binding is unavailable:
- return typed unavailable/degraded status.
- do not silently choose a random/default provider voice.

Explicit alternate voice policy may exist, but must be:
- configured
- observable
- revisioned
- clearly marked degraded/alternate

A fallback voice does not alter Character Definition; it is temporary Infrastructure presentation behavior.

#348 decides whether text-only presentation is acceptable.

---

## 20. Observability

Required metrics/events:
- synthesis queued/started/completed
- provider latency
- queue wait
- attempt count
- failure category
- cancellation
- speculative vs required synthesis
- cache hit/miss if enabled
- artifact discarded reason
- timing availability/quality
- degraded performance dimensions

Do not log full audio/raw responses or unnecessary utterance bodies merely for metrics.

---

## 21. Required tests

### Identity / mapping
- exact utterance/performance/binding match
- mismatched performance plan reject
- mismatched character voice binding reject
- provider-specific values stay outside Core DTO
- normalized intent mapping bounds/clamps

### Pronunciation
- override changes reading only, not Character text
- unknown/malformed override reject
- revision change invalidates cache identity

### Capability degradation
- unsupported pitch/rate/breathiness dimension recorded
- canonical SpeechPerformancePlan unchanged
- synthesis can succeed with degraded subset when provider permits

### Timing
- valid monotonic phoneme/mora/viseme timing
- out-of-range/non-monotonic timing reject/degrade
- timing unavailable does not fail audio unnecessarily
- no fabricated exact timing

### Failure
- unavailable
- timeout
- rate limit
- provider server error
- permanent binding/config failure
- bounded retry
- cancellation during call/retry
- secret/raw response non-leakage

### Speculation / Presentation
- speculative audio does not auto-play
- verifier rejection causes artifact discard
- stale/superseded candidate artifact not reused
- audio artifact success != actual spoken fact

### Concurrency
- slow TTS while new foreground cognition proceeds
- background speculative synthesis does not starve foreground
- shutdown leaves no pending synthesis/retry task

### Adjacent
- #331→#358 mapping
- #358→#348 artifact readiness
- #358 timing + Presentation STARTED→#340 input

---

## 22. Non-goals

- Character Voice Style design
- SpeechPerformancePlan generation
- semantic verification
- speech queue / Presentation decision
- actual playback lifecycle
- Body viseme interpolation
- fixed pronunciation-driven semantic rewriting
- provider voice ID as Character personality fact

---

## 23. Design Gate

#358 implementation starts only after:
- #331 SpeechPerformancePlan contract finalized
- #348 candidate/artifact/Presentation identity contract finalized
- #340 timing/viseme consumer contract finalized during Body design
- lifecycle/failure semantics align with #350
- #445 Design Completion Gate PASS

Until #445 PASS, no TTS production implementation is started from this design.
