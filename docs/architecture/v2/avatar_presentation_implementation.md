# #346 Avatar Presentation V2 Implementation Binding

Owner: #346
Base: `rebuild/v2-foundation@8d39b4bcb84b809e4ac23d161ff32d5530e2473b`
Canonical:
- `avatar_presentation_contracts.md`
- `body_integration_contracts.md`
- `subsystem_architecture.md`

Status: implementation binding

## 1. Resume Gate

現行V2 trunkには`app/subsystems/avatar`が存在せず、#346番号を持つbranch / PRも存在しない。

旧Avatar系PR #153 / #157 / #158 / #159 / #160 / #163等はdevelop-eraの`AvatarPerformancePlan`、旧BodyPoseFrame、またはtest-only runtimeを前提とする。V2 #346のproduction lineageとして再利用・cherry-pickせず、UI/運用上のhistorical referenceだけに限定する。

新lineage:

```text
rebuild/v2-foundation@8d39b4b...
→ feature/346-avatar-presentation
```

## 2. 実装配置

AvatarはCore DomainではなくSubsystemなので、production実装は次に置く。

```text
app/subsystems/avatar/
  contracts.py
  projection.py
  runtime.py
  stick.py
```

Core側の`BodyPoseFrame`、`BodyState`、`BodyMotionPlan`へrenderer targetやmodel parameterを追加しない。

## 3. 二段projection

#346は`BodyPoseFrame`を直接renderer SDK objectへ変換しない。

```text
BodyPoseFrame
  + AvatarModelBinding
  ↓ deterministic projector
AvatarProjectionCommand
  ↓ AvatarRendererPort
Stick / Live2D / 3D adapter
  ↓
AvatarRendererResult
  ↓
AvatarProjectionReport
```

`AvatarProjectionCommand`はSubsystem-owned DTOで、renderer target refと有限数値だけを持つ。Core semantic objectやraw speech textを含めない。

## 4. Binding generation

`AvatarModelBinding`はcanonical fieldsに加えてruntime fence用`binding_generation`と`root_joint_id`を持つ。

- `binding_revision`: 同一logical bindingの内容改訂。
- `binding_generation`: model/reload epoch。in-flight frameを世代越しに適用しないためのfence。
- `root_joint_id`: `BodyPoseFrame.pose.root_world_transform`をどのcanonical jointへ対応させるかを明示する。

binding admission時に`CanonicalBodyModel`へexact validationする。

- `canonical_body_model_id` exact match。
- `root_joint_id` exact match。
- joint bindingのcanonical IDはmodelに存在するものだけ。
- duplicate canonical ID / duplicate renderer targetを拒否。
- channel bindingもexact `RealtimeChannel` identityで一意。
- capabilityのsupported IDs/channelsはbindingと矛盾しない。

substring / fuzzy / heuristic bone discoveryは行わない。

## 5. Transform / channel mapping

### Joint

`AvatarJointBinding`は:

- canonical joint ID
- renderer target ref
- positionを投影するか
- rotationを投影するか
- supported translation axes
- supported rotation axes

を明示する。

初期baselineではCanonical coordinate値を保持し、renderer固有の追加座標変換はAdapter側の明示configへ閉じる。#346 projectorは勝手なbone axis推測を行わない。

### Channel

`AvatarChannelBinding`はcanonical `RealtimeChannel`をrenderer targetへexact mappingし、明示的なaffine mapping:

```text
renderer_value = clamp(canonical_value * scale + offset, output_min, output_max)
```

だけを行う。raw text / phoneme / semantic labelからmouth値を生成しない。

## 6. Mirror policy

Canonical joint identityは常にanatomical left/rightを維持する。

`CAMERA_HORIZONTAL` mirrorはrenderer表示座標だけをX反転する。

- position: `x -> -x`
- rotation: canonical right-handed quaternionに対してX mirror conjugation相当として `(x, y, z, w) -> (x, -y, -z, w)`
- canonical joint ID / renderer binding targetはswapしない。

mirrorはCore Body semanticsを変更しない。

## 7. Degradation

Projectorはframe内のcanonical要素を黙って捨てない。

- mappingあり: applied
- mappingなし / capability非対応: `degraded_items`へtyped string codeを残す
- 2D Stickでdepth/rotationを表示できなくてもCore unsupportedへ昇格しない

status:

- 全要求要素を適用: `APPLIED`
- 一部mapping/capability不足: `PARTIALLY_APPLIED`
- stale frame / stale binding generation: `DROPPED_STALE`
- renderer unavailable: `OUTPUT_UNAVAILABLE`
- renderer failure: `FAILED`

## 8. Backpressure runtime

`AvatarPresentationRuntime.submit_frame(frame)`は外部I/Oを行わずO(1)でlatest frameだけを保持する。

- producerはrendererをawaitしない。
- newer frameで未present frameを置換した回数をcoalesced countへ加算する。
- body_state_revisionが過去へ戻るframeをpresentation時に`DROPPED_STALE`とする。
- last successfully presented revisionはbinding generationごとに管理する。

renderer処理は`present_latest()`というconsumer側操作でのみ実行する。

## 9. Disconnect / reconnect

rendererがunavailableの場合、latest canonical frameを保持する。

- Core producerは継続。
- disconnect中の全frame historyは貯めない。
- new frameはlatestを置換する。
- reconnect後はその時点のlatest frameから再開する。

## 10. Binding reload

`reload_binding(new_binding)`:

- model compatibilityを再検証。
- generationは増加必須。
- old queued envelopeをnew generationへ無検証流用しない。
- runtimeが保持するlatest canonical frameがあれば、new generation envelopeとして再queueする。
- old generationのlast-presented revisionはnew generationのstale判定へ持ち越さない。

## 11. Stick reference adapter

`StickAvatarRenderer`はHuman Verification用のreference adapterとする。

- `AvatarProjectionCommand`だけを入力にする。
- Motion/Emotion/Attention/Speech意味を解釈しない。
- latest applied commandをread-only snapshotとして保持する。
- available/unavailableを明示切替可能。
- production CoreへStick固有parameterを逆流させない。

ブラウザ描画surfaceはこのreference adapterのsnapshotを表示するだけとし、Body motionを生成しない。

## 12. Failure truth

- renderer `APPLIED`はpresentation成功であり、Body physical truthを再定義しない。
- output unavailable/failedでもCanonical BodyStateをrollbackしない。
- renderer exception detailをrawでCoreへ返さずsanitized diagnostic codeだけをreportへ残す。
- #346がActual Execution Factを生成しない。

## 13. Automated verification

最低限:

1. exact joint/channel binding。
2. unknown/duplicate mapping拒否。
3. missing mappingはpartial degradation。
4. anatomical IDをswapせずcamera-horizontal mirror。
5. Stick 2D capability不足がCanonical contractを縮小しない。
6. stale frame revisionをdrop。
7. old binding generation envelopeをdrop / reload後latest frameをnew generationで再queue。
8. slow consumer中latest-frame coalescing。
9. unavailable中Core producer相当submit継続、reconnect後latestだけ適用。
10. mouth channelは`BodyPoseFrame.channel_values`からのみproject。
11. contracts/APIにraw speech text / phoneme parserを持たない。
12. Stick sample binding。
13. Live2D sample binding schema。
14. 3D sample binding schema。

V2 Deterministic CIのRuff / strict Mypy / full pytest / compileall / diff-check / live base freshnessをexact-head Gateとする。

## 14. Human Verification

自動contract PASS後にStick browser surfaceで確認する。

#341 actual-path Human Verificationと共用し、最低限:

- direction
- full-body coordination
- continuity / no Home reset
- spontaneous micro-motion
- gaze / blink / breath
- speech mouth channels
- interruption / transition
- output disconnect/reconnect

を目視する。

Human Verification PASS前に#346をDone扱いしない。
