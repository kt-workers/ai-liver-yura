# V2 Input Gateway Implementation Contract

Status: Issue #349 implementation canonical
Parent: `brain_architecture.md`
Foundation: `foundation_contracts.md`

## 1. 責務

Input Gatewayは、Text、Voice、Vision、Touch、UI、Subsystem等のAdapter入力を、source implementationに依存しない`NormalizedInputEvent`へ変換する。

意味、感情、salience、Goal、Attention、Activity、Body motionを決定しない。自然言語の意味Authorityは#326、主観評価は#327にある。

## 2. 入力境界

Adapterは`InputObservation`を渡す。

- `observation_id`: Adapterが付与するstable identity
- `source`: source identity / kind / availability / permission
- `modality`: text / speech / audio / vision / pointer / touch / subsystem / lifecycle / timer
- `observed_at`: timezone-aware timestamp
- `trace_id / correlation_id / causation_event_id`
- immutable JSON-compatible `payload`
- optional continuous `session`
- optional touch `contact`

SDK object、socket、image buffer、GUI event object等のraw objectはDomainへ渡さない。large binaryはprovider-neutral referenceをpayloadへ入れる。

## 3. Source state

`InputSourceState`は次を明示する。

- identity / source kind
- availability: available / degraded / unavailable / unknown
- permission: granted / denied / unknown / not_required
- capability reference

permission deniedまたはunavailableのsourceから、通常のobserved eventを生成しない。状態変化通知はtyped `InputSourceLifecycleChange`と`source_state_changed` semantic unitだけを許可する。空payload以外、session、pointer、contactを持てず、previous/current stateが異なることを検証する。

## 4. 正規化結果

成功時はFoundation `EventEnvelope`を内包する`NormalizedInputEvent`を返す。

- `event_type = input.<modality>.<semantic_unit>`
- `source = InputSourceState.source_id`
- source/modality/session/contact metadataをimmutable payloadへ格納
- revisionはcallerが渡したcurrent snapshot
- duplicate observationは新しいEventを発行せずtyped `DUPLICATE` resultを返す
- unavailable / permission denied / lifecycle violationもtyped reject resultを返す

Gatewayはraw text、transcript、typed perceptを輸送するが、その意味を分類しない。

## 5. Continuous session

高頻度sampleを心理状態更新単位へしない。

```text
START(session_id)
→ UPDATE(session_id)*
→ END(session_id) | CANCEL(session_id)
```

Invariant:

- session identityはsource内で一意
- UPDATE/END/CANCELはactive sessionのみ
- STARTのduplicateはreject
- terminal後のsampleはreject
- sample sequenceはstrictly increasing
- lifecycle transitionはdeterministic
- sample数をEmotion/Drive/Relationship deltaへ変換しない

Gatewayは各sampleをsessionへ所属させる。後続#327が利用するsemantic segment/event aggregationは、sample frequencyから心理変化量を決めない。

## 6. Touch / contact boundary

pointer情報とactual avatar/body hitを分離する。

`PointerSample`:

- normalized viewport position
- optional pressure / buttons
- source session

`ContactPercept`:

- `target_kind`: yura_body / environment / none / unknown
- optional canonical `body_region`
- hit confidence
- percept source capability / revision

pointer座標だけから「ゆらへ触れた」またはbody regionを捏造しない。actual hitがない場合は`target_kind=none/unknown`を保持する。

## 7. Orderingとidempotency

- `observation_id`はprocess共有`InputAdmissionLedger`がatomicに一度だけadmitする
- continuous lifecycleはprocess共有`InputSessionRegistry`がatomicに検証・遷移する
- event timestampはAdapter観測時刻を保持する
- arrival順とoccurred順を混同しない
- session sequenceでcontinuous orderingを保証する
- correlation / causationはFoundation contractへそのまま運ぶ
- retryは同じobservation identityを使いduplicateとして閉じる

## 8. Clean Architecture

Domain model / normalizerはProvider SDKをimportしない。Adapterがraw sourceを`InputObservation`へ変換する。Gateway outputは#326/#327/#333等がtyped contractとして利用する。

## 9. 受入条件

- modality、source identity、timestamp、correlationを損失なく正規化する
- strict JSON / immutable snapshotを維持する
- source unavailable / permission deniedをfail-closedで拒否する
- duplicateをidempotentに拒否する
- continuous session lifecycle / sequenceを検証する
- pointer sampleとactual touch/body regionを分離し、body regionはYura body hitだけに許可する
- raw SDK/source objectをDomainへ渡さない
- Meaning/Appraisal/Goal/Attention判断を含めない
- Unitで全reject reasonとsession transitionを検証する
- Adjacent contract testでFoundation EventEnvelopeとInput Meaning/Appraisal consumerへ安全に渡せることを確認する
