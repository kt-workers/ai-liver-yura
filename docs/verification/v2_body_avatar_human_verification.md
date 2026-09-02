# #341 / #346 Body・Avatar Human Verification Surface

## 1. 位置付け

この文書は Issue #341 Body Integration と Issue #346 Avatar Presentation の人間による実動作確認に使う、`test/341-346-avatar-stick-verification` 専用surfaceを定義する。

このsurfaceは製品機能ではなく検証器であり、`rebuild/v2-foundation` へマージしない。検証専用PR #544も **NEVER MERGE** とする。

固定したproduction成果:

- #341 source HEAD: `9e6de3b6950b19248b279da3d5f7499185685909`
- #346 source HEAD: `920bb3275d6a92a57d87a02b2fdefcdca99a6bbe`
- #341 production PR: #541
- #346 production PR: #542

Human Verification依頼時にはverification branchのexact HEADを別途固定する。

## 2. Browser surface方針

既存の `gui/yura-body-pose-lab` が採用していた Python HTTP server + SSE + HTML/CSS/JavaScript + Canvas の構成をhistorical referenceとして再利用する。

旧 `gui/yura-avatar-runtime-lab` の `AvatarPerformancePlan / Track` はV2 #346のCanonical `BodyPoseFrame` projection契約と異なるため使用しない。

旧Labの旧Pose schemaや旧semantic runtimeを移植せず、V2 production contractだけを検証する。

## 3. Authority境界

検証surfaceが確認する経路:

```text
検証入力
  ├─ Executive相当のbounded BODY intent
  ├─ Focus相当のBodyGazeTargetView
  └─ trusted STARTED speech + SpeechTimingTrack sample
        ↓
#338 BodyMotionPlanner / DeterministicBodyMotionPlanner
        ↓
#340 BodyRealtimeEngine
        ↓
#340 BodyRealtimeRuntime
        ↓ RealtimeOverlayBundle
#341 BodyIntegrationRuntime
        ↓
#339 BodyContinuousController / BodyStateAuthority
        ↓
BodyPoseFrame
        ↓
#346 AvatarPresentationRuntime
        ↓
#346 StickAvatarRenderer
        ↓
Browser Canvas
```

検証UIは禁止:

- `BodyState` / `BodyPose` の直接書き換え
- Canonical `RealtimeOverlayBundle` / `ChannelOverlay` の直接生成
- blink / breath / subtle sway / mouth channel値の直接指定
- renderer座標からCanonical Bodyへ意味を逆流させること
- fixed gesture名やrenderer parameterをBody intentの意味Authorityとして扱うこと
- raw speech text / phonemeからAvatar口形を直接決めること
- planner完了をphysical/realtime frame loopの進行条件にすること

Browserが指定できるgaze値は#333 Attentionそのものではなく、#340へ渡すbounded `BodyGazeTargetView` の検証入力である。Browserは最終 `RealtimeChannel` 値を指定しない。

## 4. #340 realtime入力の扱い

### Gaze

BrowserのGaze X/Yをbounded `BodyGazeTargetView`へ変換し、#340がlow-passとone-frame displacement boundを適用してCanonical `GAZE_X / GAZE_Y` channelを生成する。

### Blink

Browserからblink commandを作らない。#340 `BodyRealtimeEngine` のseed付きstate machineが自律生成する。

### Breath / subtle motion

検証用 `BodyExpressionContext` をread-only入力として#340へ渡す。breath phase/amplitudeとsubtle swayは#340が生成し、Browserはchannel値を直接指定しない。

### Speech articulation

検証surfaceはraw textから口形を作らない。typed `SpeechPresentationReport(status=STARTED)` + `PreparedAudioArtifact` + `SpeechTimingTrack` の検証sampleを#340 `RealtimeSpeechView`へ渡し、#340のcanonical articulation mappingを通す。

このsampleは **#340→#339→#346のmouth path確認用** であり、#348/#358の実TTS再生・実provider timingをHuman Verificationしたことにはしない。実音声同期の最終確認はactual Speech Presentation/TTS pathで別途必要である。

## 5. D10で確認できる範囲

現行D10 Canonical Body Modelは最小物理モデルである。

- `root`
- 右腕 `arm` のZ軸1自由度
- `chain:arm`
- `effector:hand`
- 3点support contact

今回確認できる主対象:

- 右腕の到達方向
- deliberate motionの連続性
- motion完了後のbaseline continuation / no Home reset
- planner待機中の#340 realtime継続
- #340 gaze / blink / breath / subtle / speech articulation projection
- #346 renderer disconnect/reconnectとlatest-frame policy

今回だけでは完了扱いにしない:

- 両腕協調
- 膝 / 腰 / 足首 / root / 腕を使うジャンプ
- neck / head / torsoを含む全身注意協調
- 3D full-body model固有のdepth挙動
- actual TTS音声と実SpeechTimingTrackの同期品質

2D Stick/D10制約を理由にCanonical 3D acceptanceを弱めない。

## 6. 検証モード

### 6.1 決定論Motion Planner

`DeterministicBodyMotionPlanner` を使い、#341/#339/#340/#346接続を確認する。

### 6.2 実Body Motion LLM

既存production `BodyMotionPlanner` と `OpenAIResponsesAdapter.from_environment()` を使う。

ローカル環境変数:

- `OPENAI_API_KEY`: 必須
- `YURA_VERIFY_OPENAI_MODEL`: 必須。modelをhard-codeしない

Provider candidateはproduction `parse_candidate()` と `BodyMotionPlanAuthority.commit()` を通し、不正selector / target / model / revisionはfail-closedとする。

## 7. Browser表示

最低限表示する:

- D10 Stick Canvas
- BodyState revision / frame count
- active plan / execution session
- planner status / latency
- #340 realtime runtime status / late tick count
- latest `RealtimeOverlayBundle` layer statuses
- final `BodyPoseFrame` Canonical channels
- #346 Avatar projection status
- dropped/coalesced frame数
- renderer availability
- sanitized diagnostics

Stickは#346 `AvatarProjectionCommand`だけを読み取り、Canonical stateを書き換えない。

## 8. Browser操作

- 右下〜右上のD10 target angleを選んでMotion submit
- planner mode: deterministic / real LLM
- planner delay: 0 / 5 / 20秒
- Gaze X/Y targetを変更
- trusted speech timing sampleを開始
- renderer接続 OFF / ON
- planning中に別Motionをsubmitしてsupersede

Blink / breath / subtle / final mouth opennessを直接操作するUIは置かない。

## 9. PASS候補

D10範囲で最低限:

1. deliberate motion中にBody revision/frameが連続更新される。
2. 5秒/20秒planning待ち中も#340 realtime layerとBody frameが停止しない。
3. motion完了後Home角へ強制resetせずcurrent poseからbaselineへ連続合流する。
4. Gaze target変更が#340を通って滑らかなCanonical gaze channelになる。
5. blink / breath / subtleがBrowser直指定なしで#340から生成される。
6. trusted speech timing sampleが#340を通ってmouth channelになり#346へ投影される。
7. renderer OFF中もCore Body revisionが進み、ON復帰時に過去全frameをreplayせずlatestへ復帰する。
8. new motion / supersede時にHome resetを挟まない。
9. real LLM modeではproduction BodyMotionPlanner candidateがAuthority gateを通って実行され、LLM待ち中もrealtimeが継続する。
10. UIがBodyState/Pose/ChannelOverlayを直接生成・変更していない。

## 10. FAIL例

- planner待ちでBody revisionまたは#340 layerが停止する
- motion完了直後に腕がHomeへ瞬間移動する
- Browser slider値がそのままfinal RealtimeChannel値になる
- Browserがblink/breath/mouth `ChannelOverlay`を直接生成する
- renderer切断がCore Body loopを止める
- reconnectで古いframe列を順番にreplayする
- raw textだけでmouthが直接動く
- LLM candidateがAuthority gateを迂回する
- `BodyPoseFrame`を通さずrenderer motionを生成する

## 11. Human Verification記録

残す情報:

- verification branch / exact HEAD
- #341 / #346 source HEAD
- mode（deterministic / real LLM）
- `YURA_VERIFY_OPENAI_MODEL`（API keyは記録しない）
- 実行日時
- 各checkpoint PASS / FAIL
- FAIL時の操作順・画面症状・diagnostic

Human Verification PASS前にPR #541 / #542をmergeしない。PR #544は結果に関係なくtrunkへmergeしない。
