# Avatar Runtime Web MVP 設計

## 1. 目的

ゆら専用Live2DモデルおよびVTube Studio接続を実装する前に、Coreから発行されたアバター向けActionが、交換可能なAvatar Output Pluginを経由して外部描画Runtimeへ届く縦断経路を検証する。

今回の対象は次の最小構成である。

```text
LLM / Character Response
  ↓
ActionPlan(change_expression / move)
  ↓
ExecuteActionUsecase
  ↓
AvatarOutputPlugin
  ↓ HTTP
Render上のAvatar Runtime Lab
  ↓
Canvas棒人間モデル
```

本設計は `docs/avatar-runtime-design-report` ブランチの `docs/avatar_output_avatar_runtime_design_report.md` を基準とし、Web上の超軽量検証Backendを追加する差分設計である。

## 2. ブランチ分離

### 2.1 実装ブランチ

`feature/avatar-runtime-foundation`

担当範囲：

- Core非依存のAvatar Output Port
- Avatar Output PluginのRuntime登録
- HTTP Client Adapter
- `change_expression` / `move` Actionとの接続
- 接続不能時の安全な縮退
- 単体テスト

### 2.2 検証ブランチ

`experiment/avatar-runtime-render-stick-model`

担当範囲：

- Renderで起動する検証サーバー
- Canvasで描画する棒人間モデル
- 表情・ジェスチャー・視線の簡易アニメーション
- Action受信履歴と接続状態の表示
- 手動プリセット送信
- Render Blueprint設定

検証ブランチは実装ブランチを基点とする。検証用UIや棒人間Backendを本番Live2D Runtimeへ混在させない。

## 3. 今回の契約

### 3.1 高レベル操作

CoreおよびPluginはLive2D Parameter名を扱わない。

```python
set_expression(expression: str)
play_gesture(gesture: str)
set_gaze(gaze: AvatarGazeIntent)
```

`AvatarGazeIntent` は次の意味情報だけを持つ。

- `target`: viewer / left / right / up / down / away / neutral
- `behavior`: maintain / glance / wander
- `intensity`: 0.0〜1.0

### 3.2 HTTP DTO

初期MVPでは、Pluginから検証Runtimeへ次のJSONを送信する。

```json
{
  "schema_version": 1,
  "type": "avatar.action",
  "action": "expression",
  "name": "happy",
  "intensity": 1.0
}
```

```json
{
  "schema_version": 1,
  "type": "avatar.action",
  "action": "gesture",
  "name": "small_nod",
  "intensity": 1.0
}
```

```json
{
  "schema_version": 1,
  "type": "avatar.action",
  "action": "gaze",
  "target": "viewer",
  "behavior": "maintain",
  "intensity": 0.8
}
```

送信先は `POST /api/avatar/actions` とする。

HTTPはWeb MVPを最短で検証するための暫定Transportである。最終的なAvatar Runtime Subsystemでは、完了通知、割込み、連続制御、接続監視のためWebSocketへ移行する。

## 4. Action対応

| ActionType | Avatar操作 | 値の取得元 |
|---|---|---|
| `change_expression` | `set_expression` | `ActionPlan.text` |
| `move` | `play_gesture` | `ActionPlan.text` |

現段階では新しいActionTypeを増やさない。既存のCharacter Responseから生成されるActionをそのまま使い、LLMから描画までの縦断経路を先に成立させる。

視線はPortとPlugin Capabilityを先行追加するが、Core Actionへの正式接続はAvatarPerformancePlan導入時に行う。

## 5. Runtime設定

検証機能は環境変数で明示的に有効化する。

- `YURA_AVATAR_OUTPUT_ENABLED`: `1` で有効
- `YURA_AVATAR_RUNTIME_URL`: Runtime URL。例 `https://...onrender.com`
- `YURA_AVATAR_OUTPUT_TIMEOUT_SECONDS`: HTTPタイムアウト。既定値 `3.0`

無効時またはURL未設定時はPluginを登録しない。

## 6. エラー・縮退方針

- Avatar Runtimeへ接続できなくてもCoreの会話・音声・記憶処理を停止しない。
- Adapter例外はAvatarOutputPluginがCapability unavailableへ遷移させる。
- ExecuteActionUsecaseは例外を記録し、Action実行全体をクラッシュさせない。
- 次回以降のAvatar ActionはUnavailableとして拒否される。
- 再接続・自動復旧は次段階で実装する。

## 7. Render検証モデル

棒人間はCanvas 2Dで描画し、外部画像・Live2D SDK・GPUを必要としない。

最低限の表現：

- 表情: neutral / happy / sad / surprised / angry / curious
- ジェスチャー: small_nod / head_tilt / wave / lean_forward / bounce
- 視線: viewer / left / right / up / down / away / neutral
- Idle: 呼吸に相当する微小上下動

画面には以下を表示する。

- 現在の表情・ジェスチャー・視線
- 最終Action JSON
- 受信時刻
- Action履歴
- 手動プリセットボタン

## 8. 完了条件

1. `YURA_AVATAR_OUTPUT_ENABLED=1` でCore起動時にAvatar Output Pluginが初期化される。
2. LLM出力から生成された `change_expression` がRender上のモデル表情を変える。
3. LLM出力から生成された `move` がRender上のモデルを動かす。
4. Render停止中でもCoreが継続動作する。
5. 検証用コードが本番Live2D Backendのブランチと分離されている。
6. Port、Plugin、Adapter、Action接続に単体テストがある。

## 9. 次段階

- AvatarPerformancePlan / Segmentの導入
- 相関ID、Priority、Duration、Fade、Interrupt Policy
- WebSocket双方向通信
- 自動再接続とCapability再評価
- VTubeStudioBackend
- Parameter / Hotkey一覧取得
- モデルプロファイル
- 視線の20〜30Hz補間
- ゆら専用Live2Dモデルへの切替
