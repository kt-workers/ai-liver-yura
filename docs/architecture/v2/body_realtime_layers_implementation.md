# #340 Body Realtime Layers 実装整合

対象Issue: #340

この文書は `body_realtime_layers_contracts.md` を置換しない。#340の実装が、Canonical BodyStateを変更せず、renderer非依存のRealtime overlayだけを生成することを記録する。

## 実装配置

- `app/domain/body_realtime/contracts.py`: typed gaze、Presentation開始済みspeech/timing binding、overlay bundle、layer status。
- `app/domain/body_realtime/engine.py`: 外部I/Oを持たない決定論的gaze/blink/breath/speech articulation/subtle motion生成。
- `app/domain/body_realtime/runtime.py`: bounded realtime lane、短いinput read、overlay publish Port、cancellation/shutdown。

## Authority境界

- #340は `BodyState` を読むだけであり、生成するのは `RealtimeOverlayBundle` だけである。#339はこのbundleを最終physical compositionするconsumerであり、#340は#339のController、IK、BodyState commitを実装しない。
- `BodyGazeTargetView` は空間値を持つtrusted viewだけを受ける。Focus識別子から座標を推測しない。
- `RealtimeSpeechView` は#348の `STARTED` report、#358の `PreparedAudioArtifact`、trusted `SpeechTimingTrack` のexact identityを検証する。prepared/speculative audio、未開始Presentation、timing未提供ではmouth articulationを開始しない。
- provider/renderer固有のparameter名、Avatar投影、BodyIntent、Character text解析、TTS synthesis、Speech Actual Factは含めない。

## canonical対応

| canonical節 | 実装対応 |
| --- | --- |
| 3–4 | immutable `RealtimeOverlayBundle`はbody revisionを保持し、`BodyState` mutation APIを持たない。 |
| 5 | runtimeは単一lane・target interval・late tickのbounded skipでcatch-up burstを作らず、engineは実elapsedを一tickの連続状態更新へ使う。 |
| 6–8 | typed spatial gazeだけをsmooth/saturateし、full-body orientationを生成しない。 |
| 9–10 | seedable bounded open intervalを持つlocal blink phaseとcontinuous breath phaseを保持し、amplitude/tempoをbounded transitionし、expression updateでphaseをresetしない。 |
| 11–14 | actual `STARTED` + report timing ref + artifact/timing identityだけをspeech articulationへ通す。timing unit境界はlocal articulation stateでblendし、timing欠落時はtyped degradationであり、架空mouth motionを作らない。 |
| 15–18 | seedable smooth subtle variationとlayer別statusを保持し、一層のdegradationが他層を止めない。 |
| 19–23 | engineは同期・I/Oなし、runtimeはcancellable。runtimeのmonotonic clockをengineへ渡し、outputはsource revision、layer status、actual interval/jitterを含む。breath parameterはbounded transitionで更新する。 |

## 後続境界

#339がoverlayのjoint conflict/limits/balanceを再検証して最終 `BodyState` / `BodyPoseFrame` をcommitする。#346のrenderer projection、#341のBody IntegrationはこのWorkに含めない。
