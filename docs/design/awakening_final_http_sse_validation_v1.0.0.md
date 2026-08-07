# Awakening実HTTP / SSE最終統合検証設計 v1.0.0

## 目的

Issue #199 / Parent #186 のうち、自動化できる実起動境界を固定Presetではなく因果状態の差として検証する。

対象は #196〜#198 で接続した次の経路である。

```text
Awakening Context
→ Awakening Appraisal
→ Emotion / Desire / Drive
→ Awakening Lifecycle
→ BodyAwakeningAffect
→ BodyExpressionInput
→ BodyInnerMotionState
→ BodyPoseFrame
→ HTTP / SSE
→ Body Pose Lab
```

Speech / Silenceについては、Awakening専用発話ルールを新設せず、既存Motivation / Autonomous Interaction経路を検証する。

## ブランチ構成

#199は #198 の最終統合検証であるため、`feature/awakening-final-integration` を PR #205 head から派生させる。

PR baseはCI実行のため`develop`とするが、#203 → #204 → #205 がdevelopへ順番に統合されるまで #199 PRはマージしない。

## 自動検証境界

### 1. 初期Frame

#198で追加したstartup causal seedを使用し、Body Runtimeをstartする前に評価済みEmotion / Awakening AffectをBody Providerへ反映する。

実HTTP Body Pose Lab harnessを起動し、SSEで最初に観測できるFrameが既定neutralではなく、評価済み覚醒状態由来の`inner_state`を持つことを確認する。

特定Poseや固定モーション名を期待値にしない。

### 2. Lifecycle

同一のAwakeningStateTransitionServiceで既存状態更新境界を通し、WAKING → ORIENTING → READYへ有限状態が進むことを確認する。

各phaseでBodyへのAwakening salienceが連続的に減衰し、READYで0になり通常Emotion由来Bodyへ戻ることを検証する。

### 3. 状態差

固定表情ラベルではなく、次のシナリオごとにBodyの有限`inner_state`が異なることを確認する。

- cold start
- short resume / refreshed寄り
- drowsy / low energy
- eager / high energy・curiosity
- cautious / high security

差分対象はeye openness、movement energy、gaze freedom、posture tendency、tension等の連続値とする。

### 4. 障害縮退

- Body unavailable
- TTS unavailable
- Persistence missing / corrupted / incompatible

でAwakening Context / Appraisal / Runtime状態更新が起動不能にならないことを確認する。

HTTP / SSE検証ではBody available経路を用いる。Body unavailableはRuntime単体境界で検証する。

### 5. ユーザー入力優先

覚醒中のUSER_TEXTが既存Event/Interruption経路へ入り、覚醒専用処理がユーザー入力をブロックする新規ゲートになっていないことを確認する。

## Body Pose Lab診断

既存Body Pose LabのHTTP / SSEプロトコルと表示責務を再利用する。検証専用の本番Motion名・Preset・Bodyコマンドは追加しない。

必要な診断値が既存Frameに不足する場合のみ、本文やPromptを含まない有限状態を追加する。ユーザー会話本文、Character本文、Memory本文は診断へ複製しない。

## 実画面確認

自動CIでは「HTTPサーバが起動し、SSEで実Frameを受信でき、因果状態が期待どおり変わる」までを保証する。

以下は人間によるVerificationとして残す。

1. Core + Body Pose Labを通常起動する。
2. 起動直後が完成済みneutralで固定されず、目・視線・姿勢・連続動作に覚醒差が見える。
3. WAKING → ORIENTING → READYが不連続なPreset切替ではなく自然につながる。
4. READY後も通常Emotion由来の連続Bodyが継続する。
5. 低talkativeness時に無理な発話をせず、非言語覚醒が見える。
6. 起動中にユーザー入力した場合、入力が安全に優先される。
7. Body/TTSを無効化してもCoreが起動不能にならない。

録画または画面確認結果をIssue #199へ記録し、ユーザーの明示承認後のみマージ可能とする。

## 完了判定

自動実装完了条件:

- 実HTTP / SSE回帰が追加される。
- 初期Frameの非neutral因果状態をSSEで確認できる。
- 複数Awakening状態でExpression結果差を確認できる。
- Lifecycleの減衰 / READY接続を確認できる。
- 障害縮退と入力優先の既存回帰を含む全体pytestが成功する。
- Draft PRを作成する。

その後は`Verification`とし、実画面確認・依存PR統合・ユーザー承認が揃うまでマージしない。
