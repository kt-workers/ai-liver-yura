# Voice Output Plugin Factory移行監査 v1.0.0

## 1. 目的

Games PluginのRuntime統合と並行して、Voice Output Pluginを次のFactory／Loader移行対象として扱えるかを整理する。

この監査では実装コードを変更せず、現在の依存関係、生成責務、設定入力、初期化条件、失敗時挙動、必要テストを明確にする。

## 2. 現状

`app/plugins/voice_output/__init__.py`は`VoiceOutputPlugin`の具体クラスを直接公開しており、Games Pluginのような`plugin_factory`公開は存在しない。

`VoiceOutputPlugin`は次の共有契約を受け取る。

- `SpeechSynthesizer | None`
- `AudioPlayer | None`

Plugin自身はVoiceVoxやSystem Audio Playerなどの具体Adapterを生成しない。Plugin IDは`voice_output`、Capabilityは`output.speech`である。

`initialize()`時にSynthesizerとPlayerの両方が存在する場合のみHealthyになる。片方でも欠けている場合、Pluginは登録・初期化されるがCapabilityを公開しない縮退状態になる。

音声合成失敗時はCapabilityを利用不可へ変更する。一方、音声再生失敗時は一時的なブラウザ切断などを想定し、Capabilityを維持したまま例外を再送出する。この差異はFactory移行後も維持する。

## 3. Runtime側の現在の責務

`app/bootstrap/runtime.py`は現在、概ね次の責務を持つ。

1. Speech設定を読み取る
2. `SpeechSynthesizer`具象Adapterを生成する
3. `AudioPlayer`具象Adapterを生成する
4. `VoiceOutputPlugin(speech_synthesizer, audio_player)`を直接生成する
5. Plugin Managerへ登録する
6. SynthesizerとPlayerの双方が存在する場合だけ有効として初期化する
7. 初期化後、Pluginを`ExecuteActionUsecase`へ両契約として渡す

Factory移行では、4の具体Plugin生成だけをPluginパッケージ側へ移し、1〜3のAdapter生成責務はComposition Root側に残すのが最小変更である。

## 4. 推奨Factory境界

Voice Output Plugin Factoryは具体Adapterを生成せず、`PluginFactoryContext.services`から`SpeechSynthesizer`と`AudioPlayer`を受け取る。

推奨キー名:

```python
{
    "speech_synthesizer": speech_synthesizer,
    "audio_player": audio_player,
}
```

両方または片方が`None`でも生成自体は許容する。既存Pluginが縮退初期化を実装しているため、Factoryで完全構成を強制しない。

## 5. 有効判定

Factory／Loaderの`enabled`は「Pluginモジュールをimportするか」を決める値であり、Providerの健全性判定とは分ける。

- `config.speech.enabled == False`ならVoice Output Pluginをimportしない
- `config.speech.enabled == True`ならFactory経由でPluginを生成する
- Provider生成結果が不完全ならPluginは縮退初期化される
- Runtimeの有効状態辞書には、登録済みPluginに対して`True`を渡す

## 6. 依存方向

```text
Composition Root
  -> Plugin Loader / Factory契約
  -> 文字列モジュール名 app.plugins.voice_output

Voice Output Factory
  -> Shared SpeechSynthesizer契約
  -> Shared AudioPlayer契約
  -> VoiceOutputPlugin

VoiceOutputPlugin
  -> Shared contractsのみ
```

`app/bootstrap/runtime.py`は`VoiceOutputPlugin`具体クラスを静的importしない。

## 7. 既存テストで保証される契約

`tests/test_voice_output_plugin.py`では次が保証されている。

- Shared VoiceIntent契約を利用する
- Shared SpeechSynthesizer／AudioPlayer契約を利用する
- 合成と再生を各Providerへ委譲する
- 合成失敗時にCapabilityを取り消す
- Core処理を停止せず失敗結果へ変換できる
- Plugin復旧が可能
- Provider不完全時はPluginを登録したまま縮退状態になる

Factory移行でこれらを変更してはいけない。

## 8. 追加すべきテスト

### Factory単体テスト

- servicesからSynthesizerとPlayerを受け取りPluginを生成する
- `None`を含む構成でもPluginを生成できる
- 不正型が渡された場合は明確な`TypeError`にする
- Factoryが具体VoiceVox Adapterをimportしない

### Loader／登録テスト

- Speech無効時に`app.plugins.voice_output`をimportしない
- Speech有効時にFactory経由で`voice_output`を登録する
- Provider不完全時でもPlugin登録自体は成功する
- Provider不完全時にCapabilityを公開しない

### Runtime統合テスト

- `runtime.py`から`VoiceOutputPlugin`静的importを削除できている
- Speech無効設定でCoreが起動できる
- Speech有効＋Provider正常で音声Capabilityが利用可能になる
- Speech有効＋Provider不完全でテキスト出力が維持される

## 9. 推奨PR分割

### PR 1: Voice Output Factory追加

- `app/plugins/voice_output/factory.py`
- `plugin_factory`公開
- Factory単体テスト

Runtimeは変更しない。

### PR 2: Runtime統合

Games PluginのRuntime Factory移行完了後に行う。

- `runtime.py`の`VoiceOutputPlugin`静的import削除
- Factory経由登録への置換
- 境界baseline更新
- Runtime統合テスト

### PR 3: 旧契約経路整理

必要な場合のみ別PRで行う。

- `app.ports.*`からShared contractsへの互換再export整理
- 破壊的変更は行わず、先に利用箇所を監査する

## 10. Games対応と並行可能な作業

並行可能:

- Voice Output Factory追加
- Factory単体テスト追加
- 型検証方針の確定
- Shared contracts依存の確認
- Runtime統合テスト設計

Games対応完了前に実施しない:

- `runtime.py`のVoice Output登録置換
- 境界baselineからVoice Output例外を削除
- GamesとVoice Outputを同一PRでまとめて変更

## 11. 完了条件

- `app.plugins.voice_output`が`plugin_factory`を公開する
- FactoryがShared contracts経由でProviderを受け取る
- Factoryが具体TTS／Audio Adapterを生成しない
- Speech無効時にVoice Output Pluginをimportしない
- Runtimeが`VoiceOutputPlugin`を静的importしない
- Provider不完全時の縮退挙動を維持する
- 合成失敗と再生失敗のCapability挙動差を維持する
- 既存Voice Outputテストと全体テストが成功する
