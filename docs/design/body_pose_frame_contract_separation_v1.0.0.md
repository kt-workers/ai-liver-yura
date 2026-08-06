# BodyPoseFrame契約分離 v1.0.0

## 1. 目的

旧`body_pose_frame.py`に集中していた数学プリミティブ、注意候補、運動Snapshot、骨格、BlendShape、2D補助投影、Frame集約を責務単位へ分離する。

BodyPoseFrameは棒人形、Live2D、3Dで共通利用するモデル非依存契約とし、Transport、GUI、モデル固有Parameter／Bone名を含めない。

## 2. 分離後の構成

```text
body_value_validation.py
  └─ 有限値・範囲・整数・識別子の共通検証

body_geometry.py
  ├─ BodyCoordinateSpace
  ├─ BodyVector3
  ├─ BodyQuaternion
  ├─ BodyTransform3D
  └─ BodyGazeVector

body_attention.py
  └─ BodyAttentionCandidate

body_motion_state.py
  └─ BodyInnerMotionState

body_skeleton.py
  ├─ CanonicalBodyJoint
  ├─ CANONICAL_BODY_JOINT_IDS
  └─ BodyJointPose

body_blend_shape.py
  ├─ CanonicalBodyBlendShape
  ├─ CANONICAL_BODY_BLEND_SHAPE_NAMES
  └─ BodyBlendShape

body_auxiliary_projection.py
  ├─ BodyTrackingPose
  └─ BodyTrackingVelocity

body_pose_frame.py
  ├─ BodyPoseFrame
  ├─ schema v2集約検証
  ├─ Payload変換
  └─ 旧import位置からの再公開
```

## 3. 主契約と補助契約

### 3D主契約

- `coordinate_space`
- `root_transform`
- `joints`
- `blend_shapes`
- `gaze_vector`

### 補助投影

- `pose`
- `velocity`

補助投影は棒人形やLive2D Adapterが利用できるが、3D骨格の代替ではない。

## 4. Schema

```text
schema_version = 2
coordinate_space = right_handed_y_up
```

Frameは次を保証する。

- sequenceとtimestampは非負整数
- attention dwellは非負整数
- attention targetは1〜80文字
- Joint IDはFrame内で一意
- BlendShape名はFrame内で一意
- JointとBlendShapeは型付き値のみ
- Quaternionは有限値かつ自動正規化
- Gaze directionは単位Vectorへ正規化
- 数値にNaN／Infinity／boolを許可しない

## 5. Canonicalと拡張

初期Canonical Joint:

- hips
- spine
- chest
- neck
- head
- left_upper_arm
- right_upper_arm
- left_lower_arm
- right_lower_arm

初期Canonical BlendShape:

- eye_blink_left
- eye_blink_right
- jaw_open
- mouth_smile
- mouth_frown

将来の脚・手首・指・肩・独自表情を追加できるよう、Canonical集合以外のIDも契約上は許可する。

モデル固有名の扱い:

```text
Body joint_id: head
  → VRM Adapter
  → J_Bip_C_Head

Body blend shape: jaw_open
  → Live2D Adapter
  → ParamMouthOpenY
```

CoreとBody Domainは右側のモデル固有名を知らない。

## 6. 互換性

既存利用側が次のimportを維持できるよう、`app.domain.body_pose_frame`から分割済み型を再公開する。

```python
from app.domain.body_pose_frame import (
    BodyAttentionCandidate,
    BodyInnerMotionState,
    BodyPoseFrame,
    BodyQuaternion,
    BodyTrackingPose,
)
```

Payload API:

- `as_payload()`を維持
- `to_dict()`を互換別名として追加
- Payload field名とschema v2構造を維持

## 7. 責務境界

### Domainが行うこと

- 値の正規化と検証
- モデル非依存DTO
- Frame集約の整合性
- Payload変換

### Domainが行わないこと

- EmotionやInteraction Intentionの解釈
- Attention候補の選択
- 姿勢ターゲットの計算
- 時間積分
- HTTP／WebSocket送信
- Live2D Parameter変換
- VRM Bone変換
- GUI描画

## 8. テスト

- Quaternion正規化
- NaN／Infinity／ゼロQuaternion拒否
- 正のScale
- Gaze direction正規化
- Attention候補の範囲
- Inner Motion Snapshotの0〜1境界
- Canonical名がモデル非依存であること
- 拡張Joint／BlendShapeの許可
- PoseとVelocityの別範囲
- schema v2 Payload
- coordinate space文字列互換
- Joint／BlendShape重複拒否
- 旧import位置からの再公開

## 9. 後続工程

工程5以降では、これらのDomain型を入力・出力契約として使用する。ControllerがDomain型の内部検証やPayload生成を再実装してはならない。
