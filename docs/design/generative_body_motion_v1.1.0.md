# Generative Body Motion 設計 v1.1.0

本版は`generative_body_motion_v1.0.0.md`をCore統合後の責務へ改訂する。

## 変更点

- Motion生成の所有者をBody Pose LabではなくCoreへ確定
- `BodySubsystemPort.request_motion()`を追加
- `CoreGenerativeBodyRuntime`を通常起動へ接続
- 入力意味を`body_motion_request`へ正規化
- Action Planner／UseCaseからCoreへMotionRequestを配送
- 棒人形をPose Frame表示専用モックとして分離

## 正式な実行経路

```text
StructuredInputMeaning
  ↓
BodyMotionRequestResolver
  ↓
BodyMotionRequest
  ↓
MotionAwareExecuteActionUsecase
  ↓
BodySubsystemPort.request_motion
  ↓
CoreGenerativeBodyRuntime
  ↓
GenerativeBodyMotionController
  ↓
GenerativeBodyPoseFrame
  ↓
Avatar Adapter / Stick Mock
```

`gui/yura-body-pose-lab`はController単体試験用であり、本番配線の所有者ではない。

詳細は`core_generative_body_runtime_v1.0.0.md`を参照する。
