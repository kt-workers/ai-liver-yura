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

`long_press`は`duration_ms`を追加します。`drag`は終点を`position`、始点を`start_position`として、`duration_ms`とともに送信します。座標はすべて画面内の`0.0`から`1.0`へ正規化します。

画面は感情値やEmotion Appraisalを指定しません。Coreが刺激を`AgentEvent`として評価し、感情・Drive・Reactionを決定します。
