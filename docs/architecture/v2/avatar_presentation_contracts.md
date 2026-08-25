# V2 Avatar Presentation Contracts

Owner Issue: #346
Parent: #345
Upstream: #336 / #340 / #341
Related: #348 / #358 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

#346 Avatar Subsystemは、Core Bodyが公開するimmutable `BodyPoseFrame`をLive2D / 3D / Stick等の具体モデルへ投影するPresentation責務だけを持つ。

```text
#339/#341 BodyPoseFrame
        ↓
AvatarPresentationPort
        ↓
model binding / capability projection
        ↓
Stick | Live2D | 3D renderer
        ↓
AvatarProjectionReport
```

AvatarはMotion、Emotion、Attention、Speech meaning、Activityを決めない。

---

## 2. Authority boundary

Avatarがread-only利用できる:
- `BodyPoseFrame`
- Avatar model capability/binding configuration
- presentation clock / output health
- optional speech presentation correlation metadata

Avatarが所有しない:
- BodyState
- BodyMotionPlan
- BodyExpressionContext
- cognitive Focus
- viseme生成policy
- Character/Speech semantics
- Actual Execution Fact

#340まででcanonical mouth/face channelsが生成されるため、#346がraw text/TTS phonemeから独自visemeを再計算しない。

---

## 3. AvatarModelBinding

```text
AvatarModelBinding
- binding_id
- binding_revision
- model_kind
- model_identity
- canonical_body_model_id
- joint_bindings[]
- channel_bindings[]
- mirror_policy
- capability_view
- created_at
```

`model_identity`はSubsystem内のopaque identityでありCore Body Model IDを置き換えない。

### Joint binding

```text
AvatarJointBinding
- canonical_joint_id
- renderer_target_ref
- transform_mapping
- scale_mapping?
- supported_axes[]
```

### Channel binding

```text
AvatarChannelBinding
- canonical_channel
- renderer_target_ref
- mapping
```

renderer targetはSubsystem内部だけに存在し、Core DTOへ逆流させない。

---

## 4. Binding policy

- canonical joint/channelはexact IDでbindingする。
- renderer bone/parameter名のsubstring/heuristic inferenceをproduction Authorityにしない。
- missing mappingはtyped degradationであり、近い名前へ勝手にbindしない。
- binding変更は`binding_revision`を進める。
- Canonical Body Modelが変わった場合はcompatibility再検証する。

---

## 5. Anatomical left/right and mirror

Canonicalはanatomical left/right。

Rendererがcamera mirror表示を要求する場合、`mirror_policy`で明示変換する。

禁止:
- Core Body joint identityをscreen-left/screen-rightへ変更
- Live2D表示都合でCanonical sideを反転
- modelごとにCore側のleft/right semanticsを変える

---

## 6. Capability model

Avatar modelはCanonical Bodyの全能力を表現できるとは限らない。

```text
AvatarCapabilityView
- supported_joint_ids[]
- supported_channels[]
- supported_translation_axes[]
- supported_rotation_axes[]
- max_update_rate?
- supports_3d_depth
- supports_root_translation
- supports_face_channels
```

Capabilityはrenderer limitationの記述であり、Canonical Body能力を縮退させない。

---

## 7. Projection result

```text
AvatarProjectionReport
- frame_id
- binding_id / revision
- model_identity
- status
- applied_joint_ids[]
- applied_channels[]
- degraded_items[]
- started_at
- completed_at
- dropped_or_coalesced_frames
- sanitized_diagnostics[]
```

status:

```text
APPLIED
PARTIALLY_APPLIED
DROPPED_STALE
OUTPUT_UNAVAILABLE
FAILED
```

`APPLIED`はrendererへのpresentation結果であり、Core Body motionのsemantic/physical truthを再定義しない。

---

## 8. Frame scheduling / backpressure

Avatar rendering slowdownでCore Body frame producerをblockしない。

初期policy:
- bounded queue
- realtime presentationではlatest-frame coalescingを許可
- stale intermediate framesを全部再生して遅延を蓄積しない
- frame timestamp/body revision順序を守る
- old binding revision frameをnew bindingへ無検証適用しない

`latest frame wins`はBodyState historyを削除する意味ではなく、renderer presentation queueだけのpolicy。

---

## 9. Reconnect / model reload

Output disconnect時:
- Core Bodyは継続
- Avatar healthはUNAVAILABLE/RECONNECTING等としてSubsystem内で管理
- reconnect後、current latest BodyPoseFrameからprojection再開
- disconnect期間の全frame replayを必須にしない

Model/binding reload時:
- old bindingをclose
- new binding validation
- generation/revision fence
- old in-flight reportをnew generationへ適用しない

---

## 10. Speech / mouth boundary

Avatar receives canonical mouth/face channels already produced by Body realtime.

```text
#348 Presentation STARTED
+ #358 actual timing
→ #340 canonical viseme/mouth overlay
→ #339 BodyPoseFrame
→ #346 renderer mouth parameters
```

Avatarは禁止:
- CharacterUtterance文字列からlip syncを独自推定
- speculative audioでmouth motion開始
- speech semanticsからgestureを生成

Audio playback自体はSpeech Presentation側の責務。Avatarは必要に応じpresentation correlation IDを表示同期へ利用できるが、audio truthを所有しない。

---

## 11. Stick / Live2D / 3D adapters

### Stick

検証Adapter。Canonical 3D dataのうち描画可能部分を2D等へ投影する。

Stickで表現不能なdepth/rotationをCore unsupported扱いしない。

### Live2D

model parameter mappingはbinding内。Cubism parameter名をCoreへ入れない。

### 3D

VRM/bone/transform等の具象はAdapter内。Canonical座標からrenderer座標へ明示変換する。

全Adapterは同じ`BodyPoseFrame` contractを受ける。

---

## 12. Security / resource boundary

- model file path/provider credentialをCore Domain DTOへ出さない
- browserへGitHub/provider secretを渡さない
- remote renderer connection credentialsはserver-side/Adapter config
- untrusted model metadataをCore semantic inputにしない

---

## 13. Observability

- input frame ID/body revision/timestamp
- binding revision/model generation
- projection latency
- frame drop/coalesce count
- unsupported/degraded channels
- reconnect count
- output health

raw renderer objectやsecretはtraceへ出さない。

---

## 14. Required tests

- exact joint/channel binding
- missing mapping degradation
- anatomical mirror correctness
- 2D model does not shrink Canonical contract
- stale binding generation reject
- slow renderer latest-frame coalescing
- disconnect/reconnect from latest frame
- output unavailable while Core Body continues
- canonical mouth channel projection
- no raw speech text→viseme/gesture logic
- Stick contract test
- Live2D sample binding contract
- 3D binding schema generality

Human/browser/model Verificationは自動contract後に行う。

---

## 15. #445 Gate

Avatar implementation remains frozen until #445 D1-D9 and final user confirmation PASS.
