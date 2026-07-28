# Inner-state protocols

## State telemetry

- Transport: UDP
- Producer destination: `127.0.0.1:8766`
- Encoding: UTF-8 JSON, one snapshot per datagram
- Direction: Yura core → visualizer only
- Delivery: best effort

```json
{
  "schema_version": 1,
  "observed_at": "2026-07-23T00:00:00+00:00",
  "emotion": {
    "mood": "neutral",
    "arousal": 0.5,
    "valence": 0.0,
    "talkativeness": 0.5,
    "reactive": {
      "joy": 0.0,
      "amusement": 0.0,
      "anger": 0.0,
      "sadness": 0.0,
      "fear": 0.0,
      "surprise": 0.0,
      "discomfort": 0.0,
      "emotional_pressure": 0.0
    }
  },
  "drive": {
    "curiosity": 0.5,
    "engagement": 0.5,
    "boredom": 0.0,
    "energy": 0.7
  },
  "activity": { "type": null, "active": false, "pending_count": 0 },
  "attention": { "engaged": false },
  "stream": { "status": "idle" }
}
```

入力本文、感情の原因、観測対象の名前は送信しません。PC操作観測を追加する場合も、この状態表示プロトコルへ生テキストを混在させません。

## Interaction stimulus

- Browser endpoint: `POST /api/stimuli`
- Visualizer destination: `127.0.0.1:8771/UDP`
- Direction: visualizer → Yura core
- Supported stimuli: `tap`, `double_tap`, `long_press`, `drag`
- Authority: Coreの入力Adapterが`user`を付与

```json
{
  "schema_version": 1,
  "type": "interaction_stimulus",
  "stimulus_kind": "tap",
  "position": { "x": 0.5, "y": 0.5 }
}
```

`long_press`は`duration_ms`を追加します。座標はすべて画面内の`0.0`から`1.0`へ正規化します。

`drag`は開始位置に関係なく、ドラッグ中にも継続して送信します。同じドラッグは`gesture_id`で関連付け、`gesture_phase`を`start`、`update`、`end`の順に、単調増加する`gesture_sequence`とともに送ります。`start_position`は直前のサンプル位置、`position`は現在位置、`duration_ms`はドラッグ開始からの累積時間です。

画面は描画中の粒子球を`particle_zone`の楕円として添付します。Coreは座標がこの領域へ入ったサンプルだけを接触として扱います。接触中の速度、中心からの距離、累積移動量、方向反転回数を計算し、往復を伴う適度な速さの動きを`contact_motion: stroke`として認識します。従来のメタデータを持たない単発`drag`も互換性のため受け付けます。

Coreはさらに、接触位置を粒子球に対する相対座標・上下・中心寄り／表面寄りとして表し、動きを速度帯、軌跡形状、滑らかさ、リズム、往復性、曲率、細かな揺れ、接触範囲として`touch_features`へまとめます。これは快・不快などの感情結論ではありません。Character LLMが現在感情、関係性、接触履歴と合わせて、その場の感覚や気分を判断するための観測情報です。

```json
{
  "schema_version": 1,
  "type": "interaction_stimulus",
  "stimulus_kind": "drag",
  "gesture_id": "drag-2e0f7b5a",
  "gesture_phase": "update",
  "gesture_sequence": 3,
  "start_position": { "x": 0.48, "y": 0.42 },
  "position": { "x": 0.52, "y": 0.40 },
  "duration_ms": 480,
  "particle_zone": {
    "center": { "x": 0.5, "y": 0.49 },
    "radius_x": 0.18,
    "radius_y": 0.28
  }
}
```

画面は感情値やEmotion Appraisalを指定しません。Coreが刺激を`AgentEvent`として評価し、感情・Drive・Reactionを決定します。
