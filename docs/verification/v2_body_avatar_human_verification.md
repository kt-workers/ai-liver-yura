# #341 / #346 V2 Body → Avatar Human Verification

Status: Verification-only / NEVER MERGE
Related Issues: #341, #346, #545, #546
Verification PR: #544
Verification branch: `test/341-346-avatar-stick-verification`
Current trunk: `rebuild/v2-foundation@680d45abf93f2edd37ff28dfcd71319d0f1f9cd6`
Fixed production source heads:
- #341: `a1c8f19d6e848886a58d64ded1fde59a692251e1`
- #346: `412c48227c2c8b9390f3c862a3452f0999cfb508`
- #546 production fix: merged by PR #548 as `680d45abf93f2edd37ff28dfcd71319d0f1f9cd6`

## 1. Purpose

このsurfaceは #341 Body Integration と #346 Avatar Presentation を、実際に人間がBrowser上で観測するための一時的なverification harnessである。

前回Human Verificationでは、D10右腕のvalid target `-0.65 rad` 追従中にproduction #339 dynamicsがovershootし、`BodySolverError: dynamic_limit_conflict` でBody runtimeが停止した。#546でproduction dynamicsをtarget-aware brakingへ修正し、#341 planner-delay testも通常control cadenceで再検証した。

Human Verification再実施前のmachine evidence:
- #341 V2 Deterministic CI #791 / run `33695917538`: SUCCESS / 1413 passed
- #346 V2 Deterministic CI #788 / run `33695461810`: SUCCESS / 1417 passed
- #544 final compositionは本書更新後のexact-head CIを別途PASSさせる。

このsurfaceはproductionのAuthorityを置換しない。Browser操作は検証入力を作るだけで、BodyState / joint pose / renderer parameterを直接書き換えない。

## 2. 正規検証経路

```text
bounded BODY intent
→ #338 BodyMotionPlanner / DeterministicBodyMotionPlanner

BodyGazeTargetView
+ BodyExpressionContext
+ trusted STARTED Speech Presentation / SpeechTimingTrack sample
→ #340 BodyRealtimeEngine
→ #340 BodyRealtimeRuntime
→ RealtimeOverlayBundle

BodyMotionPlan + RealtimeOverlayBundle
→ #341 BodyIntegrationRuntime
→ #339 BodyContinuousController / BodyStateAuthority
→ BodyPoseFrame
→ #346 AvatarPresentationRuntime
→ #346 StickAvatarRenderer
→ Browser HTML/JavaScript Canvas
```

Browserは`ChannelOverlay` / `RealtimeOverlayBundle`を直接生成しない。Blink / breath / subtle motion / speech articulationのCanonical channel生成は#340を通る。

## 3. 起動

repository rootで:

```bash
python -m gui.v2_body_avatar_verification.server
```

Browser:

```text
http://127.0.0.1:8769
```

依存環境をPipenvから実行する場合:

```bash
pipenv sync --dev
pipenv run python -m gui.v2_body_avatar_verification.server
```

## 4. 決定論Plannerでの必須確認

### 4.1 Continuous runtime

何も操作しない状態でも:
- `Body revision` が増え続ける
- `Frame count` が増え続ける
- #340 realtimeが`BodyRealtimeRuntime` / `BodyRealtimeEngine`である
- Blink / breath / subtle motionが自律的に継続する

### 4.2 Deliberate motion / no Home reset

右腕targetを `+0.35`, `-0.35`, `+0.65`, `-0.65` 等へ変更してMotionをsubmitする。

確認:
- current poseから連続的に移動する
- valid comfortable targetでhard limit方向へ暴走しない
- `dynamic_limit_conflict`でruntimeが停止しない
- motion終了後に初期/Home poseへ瞬間resetしない
- completed後もbaseline/realtime frameが継続する

### 4.3 Planner latency 5秒 / 20秒

Planner delayを5秒・20秒へ設定し、Motionをsubmitする。

確認:
- plannerがpending中でもphysical/realtimeが通常cadenceで進む
- Body revision / Frame countが継続する
- gaze / blink / breath / subtle motionが止まらない
- planner結果ready後にnew planへactivateする

このacceptanceはphysical tick自体を5秒/20秒止める試験ではない。machine testでもCanonical `target_control_interval_seconds` の反復tickで検証する。

### 4.4 Gaze

Gaze target X/Yを変更する。

確認:
- Browser slider値がfinal channelへ瞬間直写しされない
- #340 bounded smoothingを通って追従する
- Body motion/planner pendingと独立して更新する

### 4.5 Trusted speech timing sample

`Trusted speech timing sample` を実行する。

確認:
- typed STARTED Speech Presentation + SpeechTimingTrackが#340へ渡る
- `speech_articulation` layerがactiveになる
- mouth channelがBodyPoseFrame → #346へ投影される
- sample終了後はsourceなしへ戻る

これはactual TTS音声との同期品質試験ではない。

### 4.6 Renderer disconnect / reconnect

`Stick renderer接続`をOFFにする。

確認:
- Avatar outputはunavailableになる
- Core Body revisionは継続して増える

ONへ戻す。

確認:
- 古いframe backlogを順番に再生しない
- latest frameへ復帰する
- Body Stateをrenderer側から書き換えない

### 4.7 Planning supersede

Planner delayを5秒または20秒にし、Motionをsubmitする。planning中に別targetで再submitする。

確認:
- old planningがsupersedeされる
- stale old resultが後からControllerへ入らない
- Home resetを挟まない
- current physical/realtimeは継続する

## 5. Fatal observability

Body runtimeがfatalになった場合、単なる画面フリーズとして扱わない。

期待:
- Browser上部に `Body Runtime Fatal` bannerが表示される
- terminalへ `BODY RUNTIME FATAL: <type>: <message>` が出る
- `/api/snapshot` は最後のframe/revision/session/planner/realtime evidenceと `fatal_error` を保持する
- Browser reload/SSE切断だけの `ConnectionResetError` は不要なstack traceを出さない
- 未知のserver例外は握り潰さない

fatalが出た場合はHuman Verification FAILとして、操作手順とsnapshotを保存する。

## 6. 実Body Motion LLM

実Provider確認時だけ:

```bash
OPENAI_API_KEY='...' \
YURA_VERIFY_OPENAI_MODEL='<model>' \
python -m gui.v2_body_avatar_verification.server
```

BrowserでPlanner modeを `実Body Motion LLM` にする。

確認:
- Provider待機中も#340 / #339 realtimeは停止しない
- raw Provider出力をそのままposeへ適用しない
- #338 BodyMotionPlanner / Authority gateを通ったaccepted Planだけが#341へ入る
- Plan ready後にだけactual executionへ進む

API keyはBrowser snapshot/GitHubへ保存しない。

## 7. D10 limitation

現行D10 modelは `root + 右腕1自由度` のminimum physical modelである。

今回のStick verificationだけでは以下を完了扱いにしない:
- bilateral/full-body coordination
- jumpのhip/knee/ankle/root/arms coordination
- neck/head/torso coordination
- 3D full-body depth / self-occlusion
- actual #348/#358 TTS音声 + provider SpeechTimingTrackの同期品質

2D Stick/D10制約を理由にCanonical full-body/3D acceptanceを弱めない。

## 8. PASS / FAIL response

Human Verification完了後は:

```text
Human Verification: PASS
実Body Motion LLM: PASS / 未実施 / FAIL

気になった点:
- なし
```

異常がある場合:

```text
Human Verification: FAIL

操作:
- ...

観測:
- ...

fatal_error / snapshot:
- ...
```

Human Verification PASS前にPR #541 / #542をmergeしない。PR #544はPASS/FAILに関係なくtrunkへmergeしない。
