# Voice Output Plugin Factory移行監査 v1.0.0

## 1. 目的

Games PluginのRuntime統合と並行して、Voice Output Pluginを次のFactory／Loader移行対象として扱えるかを整理する。

この監査では実装コードを変更せず、現在の依存関係、生成責務、設定入力、初期化条件、失敗時挙動、必要テストを明確にする。

## 2. 現状の構成

### Plugin公開

`app/plugins/voice_output/__init__.py`は`VoiceOutputPlugin`の具体クラスを直接公開している。

```python
from app.plugins.voice_output.plugin import VoiceOutputPlugin

__all__ = ["VoiceOutputPlugin"]
```

現時点ではGames Pluginのような`plugin_factory`公開は存在しない。

### Plugin本体

`VoiceOutputPlugin`は次の2つの共有契約を受け取る。

- `SpeechSynthesizer | None`
- `AudioPlayer | None`

Plugin自身はVoiceVoxやSystem Audio Playerなどの具体Adapterを生成しない。具象Adapterの選択・生成はComposition Root側の責務になっている。

Plugin IDは`voice_output`、Capabilityは`output.speech`である。

### 初期化条件

`initialize()`時に、次の両方が存在する場合だけHealthyになる。

- synthesizerが`None`ではない
- playerが`None`ではない

片方でも欠けている場合、Pluginは登録・初期化されるがCapabilityを公開しない縮退状態になる。

### 失敗時挙動

音声合成失敗時はCapabilityを利用不可へ変更する。

音声再生失敗時は一時的なブラウザ切断などを想定し、Capabilityを維持したまま例外を再送出する。

この差異はFactory移行後も維持する必要がある。

## 3. Runtime側の現在の責務

`app/bootstrap/runtime.py`は現在、概ね次の責務を持つ。

1. Speech設定を読み取る
2. `SpeechSynthesizer`具象Adapterを生成する
3. `AudioPlayer`具象Adapterを生成する
4. `VoiceOutputPlugin(speech_synthesizer, audio_player)`を直接生成する
5. Plugin Managerへ登録する
6. `speech_synthesizer`と`audio_player`の双方が存在する場合だけ有効として初期化する
7. 初期化後、Pluginを`ExecuteActionUsecase`へ`SpeechSynthesizer`／`AudioPlayer`として渡す

Factory移行では、4の具体Plugin生成だけをPluginパッケージ側へ移し、1〜3のAdapter生成責務はComposition Root側に残すのが最小変更である。

## 4. 推奨Factory境界

### Factory入力

Voice Output Plugin Factoryは、設定値からVoiceVoxやPlayerを直接生成しない。

`PluginFactoryContext.services`から、次の共有契約を受け取る。

```text
speech_synthesizer
 audio_player
```

推奨キー名は以下とする。

```python
{
    "speech_synthesizer": speech_synthesizer,
    "audio_player": audio_player,
}
```

Factoryは値を共有契約として検証し、`VoiceOutputPlugin`を生成する。

### Factory出力

```python
VoiceOutputPlugin(synthesizer, player)
```

両方または片方が`None`でも生成自体は許容する。既存Pluginが縮退初期化を実装しているため、Factoryで完全構成を強制しない。

### Plugin有効判定

現状の挙動では、音声出力Pluginの有効状態は次の条件に依存する。

```python
speech_synthesizer is not None and audio_player is not None
```

ただし、Factory／Loaderの`enabled`は「Pluginモジュールをimportするか」を決める値であり、Providerの健全性判定とは分ける必要がある。

推奨方針は次の通り。

- `config.speech.enabled == False`ならVoice Output Pluginをimportしない
- `config.speech.enabled == True`ならFactory経由でPluginを生成する
- Provider生成結果が不完全ならPluginは縮退初期化される
- Runtimeの有効状態辞書には、登録済みPluginに対して`True`を渡す

これにより「機能設定の無効」と「有効だがProvider不完全」を区別できる。

## 5. 依存方向

目標とする依存方向は以下。

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

## 6. 既存テストから確認できる契約

`tests/test_voice_output_plugin.py`では、少なくとも次が保証されている。

- Shared VoiceIntent契約を利用する
- Shared SpeechSynthesizer／AudioPlayer契約を利用する
- 合成と再生を各Providerへ委譲する
- 合成失敗時にCapabilityを取り消す
- Core処理を停止せず失敗結果へ変換できる
- Plugin復旧が可能
- Provider不完全時はPluginを登録したまま縮退状態になる

Factory移行でこれらを変更してはいけない。

## 7. 追加すべきテスト

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

### 境界テスト

- Core Runtimeが`app.plugins.voice_output`を静的importしない
- Voice Output Pluginが具体TTS／Audio Adapterをimportしない
- Plugin FactoryがShared contractsにのみ依存する

## 8. 推奨PR分割

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

## 9. Games対応と並行可能な作業

Games Runtime統合を待たずに実施可能。

- Voice Output Factory追加
- Factory単体テスト追加
- 型検証方針の確定
- Shared contracts依存の確認
- Runtime統合テスト設計

Games対応完了前に実施しない。

- `runtime.py`のVoice Output登録置換
- 境界baselineからVoice Output例外を削除
- GamesとVoice Outputを同一PRでまとめて変更

## 10. 完了条件

Voice Output PluginのFactory移行完了条件は以下。

- `app.plugins.voice_output`が`plugin_factory`を公開する
- FactoryがShared contracts経由でProviderを受け取る
- Factoryが具体TTS／Audio Adapterを生成しない
- Speech無効時にVoice Output Pluginをimportしない
- Runtimeが`VoiceOutputPlugin`を静的importしない
- Provider不完全時の縮退挙動を維持する
- 合成失敗と再生失敗のCapability挙動差を維持する
- 既存Voice Outputテストと全体テストが成功する
