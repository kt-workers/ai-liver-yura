# #341 / #346 Body・Avatar Human Verification Surface

## 1. 位置付け

この文書は Issue #341 Body Integration と Issue #346 Avatar Presentation の人間による実動作確認に使う、`test/341-346-avatar-stick-verification` 専用surfaceを定義する。

このsurfaceは製品機能ではなく検証器であり、`rebuild/v2-foundation` へマージしない。検証専用PR #544も **NEVER MERGE** とする。

固定した正規成果は次のとおり。

- #341 source HEAD: `9e6de3b6950b19248b279da3d5f7499185685909`
- #346 source HEAD: `920bb3275d6a92a57d87a02b2fdefcdca99a6bbe`
- #341 production PR: #541
- #346 production PR: #542

検証surfaceのHEADは追加の検証器変更により進むため、Human Verification依頼時に改めてexact HEADを固定する。

## 2. Authority境界

検証surfaceが確認する正規経路は次だけである。

```text
検証入力
  → BodyMotionPlanningContextSnapshot
  → BodyMotionPlanner または DeterministicBodyMotionPlanner
  → BodyMotionPlanAuthority
  → BodyIntegrationRuntime
  → BodyContinuousController / BodyStateAuthority
  → BodyPoseFrame
  → AvatarPresentationRuntime
  → Stick可視化
```

検証UIは次を禁止する。

- `BodyState` / `BodyPose` の直接書き換え
- renderer座標からCanonical Bodyへ意味を逆流させること
- 固定gesture名やrenderer parameterをBody intentの意味Authorityとして扱うこと
- raw speech text / phonemeからAvatar口形を直接決めること
- planner完了を物理frame loopの進行条件にすること

Stick可視化は `AvatarProjectionCommand` を読み取って描画するだけで、意味判断を行わない。

## 3. D10で確認できる範囲

現行D10 Canonical Body Modelは次の最小物理モデルである。

- `root`
- 右腕 `arm` のZ軸1自由度
- `chain:arm`
- `effector:hand`
- 3点support contact

したがって今回のsurfaceで実画面確認できる身体運動は、主に右腕の到達方向、連続運動、停止後の連続合流、realtime channel、表示切断復帰である。

全身modelを必要とする次の項目は、今回のPASSだけで完了扱いにしない。

- 両腕協調
- 膝 / 腰 / 足首 / root / 腕を使うジャンプ
- 首 / 頭 / torsoを含む全身注意協調
- 3D full-body model固有の深度挙動

2D StickやD10最小modelの制約を理由に、Canonical 3D acceptanceを弱めない。

## 4. 検証モード

### 4.1 決定論モード

外部Providerを使わず `DeterministicBodyMotionPlanner` を使う。

目的は次の機械・目視確認である。

- #341 physical frame loopと#346 projectionの接続
- 右腕の目標方向変更
- planning待機中もframe revisionが進むこと
- gaze / blink / breath / mouth等のCanonical realtime channelがAvatarへ投影されること
- deliberate motion完了後にHomeへresetせず、現在状態からbaseline continuationへ移ること
- renderer unavailable中もCore Bodyが進み、復帰時にlatest frameだけを再表示すること

### 4.2 実Body Motion LLMモード

既存の `BodyMotionPlanner` と `OpenAIResponsesAdapter.from_environment()` を使う。

必要な秘密情報はローカル環境だけから読む。

- `OPENAI_API_KEY`: 必須
- `YURA_VERIFY_OPENAI_MODEL`: 検証に使うmodel名。未指定を許可せず、検証者が明示する

検証器はProvider model名をhard-codeしない。

Role ID / 入出力schema ID / authority gateはproduction `app.domain.body_motion_planning.planner` の定義をそのまま使う。検証器側にBody Motionの別Authorityを作らない。

実LLMへは現在のCanonical Body Model、Body State、Expression、Executive由来intent、capabilityを渡す。返却candidateはproduction `parse_candidate()` と `BodyMotionPlanAuthority.commit()` を必ず通す。不正selector、target、model、revision等はfail-closedとする。

## 5. Provider出力契約

検証器がOpenAI Responses Adapterへ登録するJSON Schemaは、production `parse_candidate()` が要求する `body.motion-planning.candidate.v1` のexact shapeだけを許可する。

必須top-level field:

- `candidate_id`
- `request_id`
- `source_decision_id`
- `source_intent_id`
- `revisions`
- `body_model_id`
- `planning_body_state_revision`
- `planning_expression_revision`
- `planning_constraints`
- `goals`
- `phases`
- `coordination_constraints`
- `expression_bindings`

Providerへのinstructionは、入力payloadに存在するID / revision / constraint / capability / targetだけを使用し、Canonical joint angleやrenderer parameterを生成しないよう要求する。

## 6. 表示surface

PyQt6の検証画面に最低限次を表示する。

- Stick canvas
- current Body State revision
- active plan / trajectory
- execution session status
- latest Avatar projection status
- coalesced / dropped frame数
- realtime channel値
- planner状態と直近latency
- renderer available / unavailable
- sanitized diagnostics

Stick canvasはD10 modelを次のように表示する。

- `root`: 身体中心
- `arm`: rootから伸びる右腕segment
- end effector: 右手先
- target: 現在選択した到達目標

描画位置はpresentation commandの結果から計算し、Canonical stateを書き換えない。

## 7. 操作

最低限次の検証操作を用意する。

- 右上 / 右 / 右下等、D10 arm可動域内の目標方向を選択してplanningをsubmit
- planner delayを 0 / 5 / 20 秒に設定
- gaze channelを変化
- blink / breath / mouth opennessを変化
- renderer接続をOFF / ON
- 新しいmotionをsubmitして旧planningをsupersede
- session / diagnosticを画面で確認

実LLMモードでも、Executive相当intentは「右腕を指定されたtargetへ向ける」というD10で実行可能な意味に限定し、Providerへrenderer操作を依頼しない。

## 8. PASS条件

今回のD10範囲で次をすべて目視できればPASS候補とする。

1. deliberate motion中にframeが連続更新される。
2. 5秒 / 20秒planning待ち中もBody frameとrealtime channelが停止しない。
3. motion完了後にHome角へ強制resetせず、現在poseから連続的にbaselineへ合流する。
4. gaze / blink / breath / mouth等のCanonical channelがplanner待ちとは独立して更新できる。
5. rendererを切断してもCore Body revisionは進み、復帰時に過去全frameをreplayせずlatest frameへ復帰する。
6. new motion / supersede時に表示が不連続なHome resetを挟まない。
7. 実LLMモードでproduction `BodyMotionPlanner` のcandidateがAuthority gateを通って実行され、LLM待ち中もrealtimeが継続する。
8. UIが直接Body StateやPoseを変更していない。

## 9. FAIL例

次はFAILとして扱う。

- planner待ちでStick / Body revision / realtime channelが停止する
- motion完了直後に腕がHomeへ瞬間移動する
- renderer切断がCore Body loopを停止させる
- reconnectで古いframe列を順番にreplayする
- raw text入力だけでmouthが直接動く
- LLM candidateが不正なのにAuthority gateを迂回して実行される
- `BodyPoseFrame`を通さずUIが直接renderer motionを生成する

## 10. 記録

Human Verification時は次を残す。

- verification branch / exact HEAD
- production source heads #341 / #346
- 使用mode（deterministic / real LLM）
- `YURA_VERIFY_OPENAI_MODEL` の値（API keyは記録しない）
- 実行日時
- 各checkpointのPASS / FAIL
- FAIL時の操作順、画面症状、diagnostic

Human Verification PASS前にPR #541 / #542をmergeしない。PR #544は結果に関係なくtrunkへmergeしない。
