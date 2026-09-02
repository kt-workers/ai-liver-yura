# V2 Body / Avatar Browser Verification

Issue #341 / #346 のHuman Verification専用Browser surfaceです。

このディレクトリは `test/341-346-avatar-stick-verification` とPR #544だけで使用し、`rebuild/v2-foundation`へはマージしません。

## 起動

```bash
python -m gui.v2_body_avatar_verification.server
```

既定URL:

```text
http://127.0.0.1:8769
```

## 実Body Motion LLMを使う場合

```bash
OPENAI_API_KEY=... \
YURA_VERIFY_OPENAI_MODEL=<model> \
python -m gui.v2_body_avatar_verification.server
```

API keyはGitHub、Browser snapshot、Human Verification結果へ記録しません。

## 正規経路

```text
Executive相当のbounded BODY intent
→ BodyMotionPlanner / DeterministicBodyMotionPlanner

Focus相当のBodyGazeTargetView
+ read-only BodyExpressionContext
+ trusted STARTED speech / SpeechTimingTrack sample
→ #340 BodyRealtimeEngine
→ #340 BodyRealtimeRuntime
→ RealtimeOverlayBundle

BodyMotionPlan + RealtimeOverlayBundle
→ #341 BodyIntegrationRuntime
→ #339 BodyContinuousController / BodyStateAuthority
→ BodyPoseFrame
→ #346 AvatarPresentationRuntime
→ #346 StickAvatarRenderer
→ Browser Canvas
```

Browserは`AvatarProjectionCommand`を可視化するだけで、BodyState/Poseを直接変更しません。Browserから直接`ChannelOverlay`や`RealtimeOverlayBundle`を生成しません。

## Browser操作

- Planner mode: `決定論` / `実Body Motion LLM`
- Planner delay: `0秒` / `5秒` / `20秒`
- D10右腕target: 右下〜右上
- Gaze target X/Y: `BodyGazeTargetView`用のbounded入力
- `Trusted speech timing sample`: typed STARTED Presentation + `SpeechTimingTrack` を#340へ渡す検証sample
- `Stick renderer接続`: disconnect/reconnect確認

Blink / breath / subtle sway / final mouth opennessはBrowserから指定できません。これらのCanonical channelは#340が生成します。

## 確認ポイント

- 5秒/20秒planner待ち中もBody revisionと#340 realtimeが進む
- Gaze targetが瞬間的にchannelへ直写しされず、#340のbounded smoothingを通る
- Blink / breath / subtle motionが自律的に継続する
- trusted speech timing sampleが#340 speech articulationを通ってmouth channelへ投影される
- deliberate motion完了後にHomeへresetせずbaseline continuationへ移る
- renderer切断中もCore Bodyが進み、再接続時はlatest frameから復帰する
- planning中の別Motion submitで旧planningをsupersedeできる

## Speech sampleの境界

`Trusted speech timing sample` は #340 → #339 → #346 のmouth projection pathを確認するためのtyped sampleです。

これは実TTS再生や#348/#358 actual provider timingのHuman Verificationではありません。実音声と口形の同期品質はactual Speech Presentation/TTS pathで別途確認が必要です。

## 旧Labとの関係

旧 `gui/yura-body-pose-lab` のHTML / SSE / Canvas構成をhistorical referenceとして踏襲しています。

旧 `gui/yura-avatar-runtime-lab` の`AvatarPerformancePlan` / Track合成契約はV2 #346と異なるため使用していません。

## D10の制限

現行D10 modelは`root + 右腕1自由度`です。Canvasの頭・胴・脚は表示用scaffoldであり、次は今回のPASSだけでは完了扱いにしません。

- 両腕協調
- 膝 / 腰 / 足首 / root / 腕を使うジャンプ
- neck / head / torsoを含む全身注意協調
- 3D full-body depth
- actual TTS音声と実SpeechTimingTrackの同期品質

2D Stick/D10の制約を理由にCanonical 3D acceptanceを弱めません。
