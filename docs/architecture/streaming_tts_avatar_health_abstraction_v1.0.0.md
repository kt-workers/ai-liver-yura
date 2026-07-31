# Streaming TTS／Avatar Health抽象化 v1.0.0

## 1. 結論

Streaming SubsystemがTTSとAvatarの可用性を参照するため、中立DTO、
読み取り専用Port、Null／Static／Composite Providerを追加する。
VOICEVOX合成、音声再生、Live2D rendering、表情・motion操作は移動しない。

未接続は例外ではなく`disconnected`として返す。TTS／Avatarが未接続または劣化しても
Streaming Subsystem自身とOBS／YouTubeが正常なら、Subsystemの`healthy=true`を
維持する。

## 2. 監査分類

| 分類 | 対象 |
| --- | --- |
| Streaming公開契約へ追加 | `DependencyKind`、`DependencyState`、`StreamingDependencyHealth`、TTS／Avatar availability capability |
| Subsystem内部Port／Adapter | `DependencyHealthProvider`、Catalog、Service、Null／Static／Composite Provider |
| Core側に残す | `app/adapters/tts/**`、speech synthesis／audio playback、`AvatarOutputPort`、既存VOICEVOX／Avatar preparation health |
| 今回対象外 | TTS／Live2D実装移動、発話／Avatar操作Command、Session／Comment、Admin、Core Integration |
| 将来削除候補 | Core側Streaming preparation専用TTS／Avatar Health Portと互換composition |

## 3. 公開契約

`StreamingDependencyHealth`は次だけを公開する。

- 種別: `tts`／`avatar`
- 状態: `disconnected`／`unavailable`／`ready`／`degraded`／`error`
- `healthy`、`available`、安全なmessage、timezone付き確認時刻
- 対応する中立availability capability
- JSON互換かつ防御的にfreezeしたmetadata

未知状態は`degraded`へ正規化する。metadataはspeaker ID、endpoint、model path、
Cubism parameter、SDK response、credentialを受け付けない。SDK型と例外文は公開DTOへ
含めない。

## 4. Providerと障害分離

Null Providerは未接続状態を返し、外部I/Oも例外も発生させない。Static Providerは
テストおよび将来のIntegration入力に使用する。CompositeはTTS、Avatarの順で決定的に
集約し、一方のProviderが例外を送出しても、その依存だけを`error`へ変換して他方を返す。

## 5. Process Shell接続

Application APIは単一依存queryと一覧queryを公開する。Subsystem Healthのcomponentへ
`tts`／`avatar`を追加し、利用可能な依存だけをSubsystem Capabilityへ反映する。
dependency componentのfalseはSubsystem本体のhealthy判定をfalseにしない。

Composition Rootの既定値は両方のNull状態であり、Core adapter、VOICEVOX／Live2D SDK、
GUI、Adminをimportしない。Coreから実Healthを供給する配線は今回行わない。

## 6. 次工程

- G4: Config／Secret最終移動
- H: Session／Comment／Run of Show移動
- I/J: Streaming Admin接続先変更とCore Integration置換
- K: 旧Health Portと旧Streaming構造の削除
