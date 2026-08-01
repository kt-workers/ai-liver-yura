# 旧Streaming構造の物理削除 v1.0.0

## 結論

工程Kで、A〜Jにより利用停止した旧Streaming Plugin、Core側Adapter、専用Port、
bootstrap、Config、Admin互換を物理削除した。配信実装の所有者は
`subsystems/streaming`だけであり、Coreは`app/integrations/streaming`の公開境界だけを使う。

```text
Core:  app/integrations/streaming/**
          ↓ HTTPまたはNull Gateway
配信:  subsystems/streaming/**
          ↑
管理:  gui/yura-streaming-admin/**
```

## 削除監査

| 分類 | 対象 | 結果 |
| --- | --- | --- |
| 削除 | 旧YouTube Streaming Plugin一式 | packageごと物理削除 |
| 削除 | Core側Streaming／YouTube／OBS Adapter | packageごと物理削除 |
| 削除 | Streaming／YouTube／Comment専用global Port | canonical Subsystem Portへ統一 |
| 削除 | 旧Streaming bootstrap／runtime factory export | Core起動経路から除去 |
| 削除 | Core AppConfigのStreaming／YouTube／OBS所有 | Subsystem Configへ統一 |
| 削除 | Core Adminの配信route／read model | Core health等の汎用管理だけ維持 |
| 削除 | Admin旧client alias／旧環境変数fallback | Subsystem Admin clientへ統一 |
| 維持 | CoreのEvent／Activity／Plugin Host／observability | Core汎用責務 |
| canonical | `subsystems/streaming/**` | 配信のDomain、Application、Port、Adapter、Admin |
| canonical | `app/integrations/streaming/**` | Core側の薄い接続境界 |
| 再配置 | Fake音声出力 | `app/adapters/tts/fake_output.py` |
| 履歴 | 過去の移行監査文書 | 当時の状態を示す記録として維持 |

## Core AdminとConfig

Core Adminはhealth、diagnostics、settings、manual checkだけを提供する。YouTube認証、OBS、
Session、Run of Show、CommentはStreaming Subsystem Admin APIが提供する。Core設定には接続先、
timeout、enable、reconnect、token参照だけを環境変数として残し、OAuthやOBS passwordなどの
配信Secretを持たない。

## 完了条件

- 旧packageと互換moduleはimport不能
- Core production codeからSubsystem実装と外部SDKへのimportは0件
- CoreはSubsystemとSDKをblockしてimport可能
- SubsystemはCore Runtimeと旧Pluginなしで`--check`可能
- Streaming AdminはSubsystem clientと正規環境変数だけを使用
- migration baselineは空集合
- 全15工程（A〜K）完了、残り0
