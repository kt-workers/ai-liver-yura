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

API keyはGitHub、ログ、Human Verification結果へ記録しません。

## 正規経路

```text
BodyMotionPlanner / DeterministicBodyMotionPlanner
→ BodyIntegrationRuntime
→ BodyContinuousController / BodyStateAuthority
→ BodyPoseFrame
→ AvatarPresentationRuntime
→ StickAvatarRenderer
→ Browser Canvas
```

Browserは`AvatarProjectionCommand`を可視化するだけで、BodyState/Poseを直接変更しません。

## 旧Labとの関係

旧 `gui/yura-body-pose-lab` のHTML / SSE / Canvasという構成をhistorical referenceとして踏襲しています。

旧 `gui/yura-avatar-runtime-lab` の`AvatarPerformancePlan` / Track合成契約はV2 #346と異なるため使用していません。

## 注意

現行D10 modelは`root + 右腕1自由度`です。Canvasの頭・胴・脚は表示用scaffoldであり、全身physical acceptanceの証拠にはしません。
