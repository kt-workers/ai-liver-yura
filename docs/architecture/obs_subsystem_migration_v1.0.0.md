# OBS Subsystem移行 v1.0.0

## 1. 結論

OBS WebSocket接続、配信出力操作、Scene／Input操作、状態・例外mapping、
Fake／disabled実装の正本を`subsystems/streaming/adapters/obs/`へ移動する。
旧`app/adapters/obs/`はdeprecatedな一方向re-exportとして当面維持する。

## 2. 監査分類

| 分類 | 対象 |
| --- | --- |
| Subsystemへ移動 | OBS client factory、read-only preparation、stream control、status/error mapper、Fake／disabled、bundle、OBS設定境界 |
| Coreに残す | Stream Session、Preparation use case、既存Port、Run of Show、Core Config互換読込 |
| 一時互換path | `app/adapters/obs/**`、`app/adapters/streaming/fake_obs_preparation_adapter.py`、`fake_streaming_control.py`のOBS export |
| 対象外 | YouTube再設計、Streaming Admin、Session全面移動、Core Gateway全面置換、旧Plugin削除 |

## 3. 所有境界

Subsystem内のOBS bundleは`fake`、`obs_websocket`、`disabled`を独立に選択する。
YouTube bundleをimportせず、一方がdisabledでも他方を構築できる。Core側の既存
Composition Rootは移行期間の互換入力を保持するが、新規OBS具象importはSubsystem
pathを使用する。Runtime全面置換は後続工程とする。

`obsws_python`はclient生成時だけ遅延importする。host、port、timeout、
passwordを格納する環境変数名は`subsystems/streaming/config/obs.py`で扱い、
password値をDTO、repr、ログ、例外へ含めない。既存Core Config schemaは今回追加・
削除せず、最終移動はG4へ分離する。

## 4. 状態と操作

内部OBS状態は公開境界で次のように正規化する。

| OBS内部状態 | StreamingStatus |
| --- | --- |
| disconnected | unavailable |
| idle | ready |
| starting | starting |
| active | live |
| stopping | stopping |
| reconnecting／unknown | degraded |
| failed | error |

配信start／stopは既存の冪等性と状態待機を維持する。Scene切替とInput mute操作も
同じ直列化されたclient境界を通す。SDK responseと例外は外へ返さず、
authentication／connectionは`unavailable`、timeoutは`timeout`、不正状態は
`conflict`、未対応操作は`unsupported_operation`へ正規化する。

## 5. Composition Rootと互換性

Streaming Subsystem Composition RootはOBS bundleとYouTube bundleを別々に構築し、
healthの`obs`／`youtube` componentへ反映する。Fake／disabledでは外部I/Oを行わず、
real bundle構築だけではSDKもcredential値も読み込まない。

旧class名とimport pathは同一Subsystem実装へ解決する。旧pathに実装classやSDK
importを残さず、循環importを防ぐ。

## 6. 次工程

- G3: TTS／Avatar Health抽象化
- G4: Core Config／Secret互換読込の最終移動
- H: Session／Preparation／Run of ShowのSubsystem移動
- I/J: Streaming Admin接続先変更とCore Integration置換
- K: 旧pathと旧Streaming構造の削除
